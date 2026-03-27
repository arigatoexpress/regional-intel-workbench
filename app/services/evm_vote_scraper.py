from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass

from playwright.async_api import Browser, Page, Playwright, async_playwright

from app.models import KeyStat, PoolOpportunity, ProtocolSnapshot
from app.utils import (
    clean_text,
    format_number_compact,
    make_pool_key,
    parse_countdown_to_ms,
    parse_metric_or_zero,
    parse_vote_window,
)


@dataclass(frozen=True)
class EvmProtocolConfig:
    id: str
    name: str
    chain: str
    vote_power_symbol: str
    url: str
    source: str


PROTOCOLS = (
    EvmProtocolConfig(
        id="blackhole",
        name="Blackhole",
        chain="Avalanche",
        vote_power_symbol="veBLACK",
        url="https://blackhole.xyz/vote",
        source="Blackhole live vote page",
    ),
    EvmProtocolConfig(
        id="supernova",
        name="Supernova",
        chain="Ethereum",
        vote_power_symbol="veNOVA",
        url="https://supernova.xyz/vote",
        source="Supernova live vote page",
    ),
)


async def fetch_evm_protocol_snapshots() -> list[ProtocolSnapshot]:
    async with async_playwright() as playwright:
        browser = await _launch_browser(playwright)
        try:
            results = []
            for config in PROTOCOLS:
                page = await browser.new_page()
                await _block_noise(page)
                try:
                    results.append(await _scrape_protocol(page, config))
                finally:
                    await page.close()
            return results
        finally:
            await browser.close()


async def _launch_browser(playwright: Playwright) -> Browser:
    chromium = playwright.chromium
    launch_errors: list[str] = []
    launch_options = {"headless": True}
    candidates: list[dict[str, object]] = []

    configured_executable = os.getenv("VE_MONITOR_CHROMIUM_EXECUTABLE")
    if configured_executable:
        candidates.append({"executable_path": configured_executable, **launch_options})

    if sys.platform == "darwin":
        candidates.extend(
            [
                {"channel": "chrome", **launch_options},
                {"executable_path": "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", **launch_options},
            ]
        )
    elif sys.platform.startswith("linux"):
        candidates.extend(
            [
                {"executable_path": "/usr/bin/chromium", **launch_options},
                {"executable_path": "/usr/bin/chromium-browser", **launch_options},
                {"executable_path": "/snap/bin/chromium", **launch_options},
            ]
        )

    candidates.append(launch_options)

    for candidate in candidates:
        try:
            return await chromium.launch(**candidate)
        except Exception as exc:  # noqa: BLE001
            launch_errors.append(str(exc))

    message = "Unable to launch a browser for vote scraping. Try `python -m playwright install chromium`."
    if launch_errors:
        message = f"{message} Last error: {launch_errors[-1]}"
    raise RuntimeError(message)


async def _block_noise(page: Page) -> None:
    async def handler(route):
        request = route.request
        if request.resource_type in {"image", "font", "media"}:
            await route.abort()
            return
        await route.continue_()

    await page.route("**/*", handler)


async def _scrape_protocol(page: Page, config: EvmProtocolConfig) -> ProtocolSnapshot:
    await page.goto(config.url, wait_until="domcontentloaded", timeout=45_000)
    await page.locator("div.liquidity-pool-cell").first.wait_for(timeout=45_000)
    await page.wait_for_timeout(1_500)

    meta = await _extract_page_meta(page)
    total_pages = max(meta["total_pages"], 1)
    all_rows: list[dict] = []
    seen_pages: set[int] = set()

    while True:
        current_page = await _selected_page(page)
        if current_page in seen_pages:
            break
        seen_pages.add(current_page)
        rows = await _extract_rows(page)
        for row in rows:
            row["source_page"] = current_page
        all_rows.extend(rows)
        if current_page >= total_pages:
            break
        await _goto_next_page(page, current_page + 1)

    vote_cast, vote_capacity = parse_vote_window(meta["total_votes"])
    key_stats = [
        KeyStat(label="Votes cast", value=_format_vote_window(meta["total_votes"])),
        KeyStat(label="Total fees", value=meta["summary_map"].get("Total Fees", "--")),
        KeyStat(label="Total rewards", value=meta["summary_map"].get("Total Rewards", "--")),
        KeyStat(label="Total incentives", value=meta["summary_map"].get("Total Incentives", "--")),
        KeyStat(label="Total emissions", value=meta["summary_map"].get("Total Emissions", "--")),
        KeyStat(label="Pages scraped", value=str(total_pages)),
    ]

    pools: list[PoolOpportunity] = []
    for raw in all_rows:
        fees = parse_metric_or_zero(raw.get("fees"))
        total_rewards = parse_metric_or_zero(raw.get("total_rewards"))
        incentives = parse_metric_or_zero(raw.get("incentives"))
        if incentives == 0.0 and total_rewards >= fees:
            incentives = max(total_rewards - fees, 0.0)
        pools.append(
            PoolOpportunity(
                rank=0,
                pool_key=make_pool_key(raw.get("name"), raw.get("fee_tier")),
                name=raw.get("name") or "Unknown pool",
                fee_tier=raw.get("fee_tier"),
                tvl_usd=parse_metric_or_zero(raw.get("tvl")),
                fees_usd=fees,
                incentives_usd=incentives,
                total_rewards_usd=total_rewards,
                apr=parse_metric_or_zero(raw.get("apr")),
                current_votes=parse_metric_or_zero(raw.get("votes")),
                vote_share_pct=parse_metric_or_zero(raw.get("vote_share")),
                ranking_score=parse_metric_or_zero(raw.get("apr")),
                source_page=raw.get("source_page"),
            )
        )

    pools.sort(key=lambda pool: (pool.ranking_score, pool.total_rewards_usd or 0.0), reverse=True)
    for index, pool in enumerate(pools, start=1):
        pool.rank = index

    notes = [
        "Ranked from the live vote page by displayed vAPR.",
        f"Scraped all visible vote pages ({total_pages}) for this protocol.",
    ]
    if vote_cast is not None and vote_capacity is not None:
        notes.append(
            f"Votes cast: {format_number_compact(vote_cast)} of {format_number_compact(vote_capacity)}."
        )

    return ProtocolSnapshot(
        id=config.id,  # type: ignore[arg-type]
        name=config.name,
        chain=config.chain,
        vote_power_symbol=config.vote_power_symbol,
        ranking_basis="Ranked by the protocol's live vAPR on its vote page.",
        source=config.source,
        epoch_label=meta["epoch_label"],
        countdown=meta["countdown"],
        ends_at_ms=parse_countdown_to_ms(meta["countdown"]),
        key_stats=key_stats,
        notes=notes,
        pools=pools,
    )


async def _extract_page_meta(page: Page) -> dict:
    return await page.evaluate(
        """() => {
            const text = (selector) => document.querySelector(selector)?.textContent?.trim() ?? "";
            const summaryCells = [...document.querySelectorAll(".right-section-data-cell")].map((cell) => ({
              label: cell.querySelector(".right-section-cell-text")?.textContent?.trim().replace(":", "") ?? "",
              value: cell.querySelector(".liquidity-pool-stats-value")?.textContent?.trim() ?? "",
            }));
            const summaryMap = Object.fromEntries(summaryCells.map((item) => [item.label, item.value]));
            const pageNumbers = [...document.querySelectorAll(".pagination .item")]
              .map((item) => (item.textContent || "").trim())
              .filter((item) => /^\\d+$/.test(item))
              .map((item) => Number(item));
            return {
              epoch_label: text(".pending-time-text"),
              countdown: text(".pending-time.clickable"),
              total_votes: text(".total-votes"),
              total_pages: pageNumbers.length ? Math.max(...pageNumbers) : 1,
              summary_map: summaryMap,
            };
        }"""
    )


async def _extract_rows(page: Page) -> list[dict]:
    return await page.locator("div.pools-list > div.liquidity-pool-cell").evaluate_all(
        """(rows) => rows.map((row) => {
            const text = (selector) => row.querySelector(selector)?.textContent?.trim() ?? "";
            return {
              name: text(".details .name"),
              fee_tier: text(".bottom-info .gas-info .text"),
              tvl: text(".liquidity-pool-cell-data:nth-of-type(1) .voting-pool-data.total"),
              fees: text(".liquidity-pool-cell-data:nth-of-type(2) .voting-pool-data.total"),
              incentives: text(".liquidity-pool-cell-data.incentives .voting-pool-data"),
              total_rewards: text(".liquidity-pool-cell-data.total-rewards .voting-pool-data.total"),
              apr: text(".liquidity-pool-cell-data.last .first"),
              votes: text(".liquidity-pool-cell-data.end .voting-pool-data.total"),
              vote_share: text(".liquidity-pool-cell-data.end .votes-percentage"),
            };
        })"""
    )


async def _selected_page(page: Page) -> int:
    raw = await page.locator(".pagination .item.selected").inner_text()
    match = re.search(r"\d+", raw)
    return int(match.group(0)) if match else 1


async def _goto_next_page(page: Page, next_page: int) -> None:
    await page.evaluate(
        """(targetPage) => {
            const items = [...document.querySelectorAll(".pagination .item")];
            const direct = items.find((item) => (item.textContent || "").trim() === String(targetPage));
            const fallback = items.find((item) => item.classList.contains("extreme") && item.classList.contains("right"));
            (direct || fallback)?.click();
        }""",
        next_page,
    )
    await page.wait_for_function(
        """(targetPage) => {
            const selected = document.querySelector(".pagination .item.selected");
            return selected && selected.textContent && selected.textContent.trim() === String(targetPage);
        }""",
        arg=next_page,
        timeout=15_000,
    )
    await page.wait_for_timeout(500)


def _format_vote_window(raw: str) -> str:
    cleaned = clean_text(raw)
    if not cleaned:
        return "--"
    left, right = parse_vote_window(cleaned)
    if left is None:
        return cleaned
    if right is None:
        return format_number_compact(left)
    return f"{format_number_compact(left)} / {format_number_compact(right)}"
