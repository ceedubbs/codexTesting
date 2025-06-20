"""clean_coaches.py
A script to purge outdated contacts from college golf coaches lists.

README:
    $ pip install -r requirements.txt
    $ python clean_coaches.py --help
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from dataclasses import dataclass
from email.utils import parseaddr
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import requests
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from rapidfuzz import fuzz
from tenacity import retry, wait_fixed, stop_after_attempt
from tqdm import tqdm
import smtplib


SEARCH_URL = "https://scoreboard.clippd.com/teams/search"
LOGGER = logging.getLogger(__name__)


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler("cleanup.log"),
            logging.StreamHandler(),
        ],
    )


def load_data(
    men_master: Path,
    women_master: Path,
    men_valid: Path,
    women_valid: Path,
) -> pd.DataFrame:
    """Load and merge master lists with deliverability flags."""

    LOGGER.info("Loading CSV files")
    men_df = pd.read_csv(men_master)
    women_df = pd.read_csv(women_master)
    master_df = pd.concat([men_df, women_df], ignore_index=True)

    men_valid_df = pd.read_csv(men_valid)
    women_valid_df = pd.read_csv(women_valid)
    valid_df = pd.concat([men_valid_df, women_valid_df], ignore_index=True)
    if "deliverability_flag" not in valid_df.columns:
        valid_df["deliverability_flag"] = "valid"

    merged = master_df.merge(valid_df, on="email", how="left")
    merged["deliverability_flag"].fillna("invalid", inplace=True)
    return merged


@retry(wait=wait_fixed(2), stop=stop_after_attempt(3))
def smtp_probe(email: str) -> bool:
    """Return True if soft bounce (5xx) is detected."""

    domain = email.split("@")[1]
    try:
        with smtplib.SMTP(domain, timeout=10) as smtp:
            smtp.helo("example.com")
            code, _ = smtp.mail("<>")
            if code >= 500:
                return True
            code, _ = smtp.rcpt(email)
            return code >= 500
    except Exception as exc:  # noqa: BLE001
        LOGGER.debug("SMTP probe failed for %s: %s", email, exc)
        return False


def optional_smtp_probe(df: pd.DataFrame) -> pd.DataFrame:
    """Run SMTP probe for catch-all addresses."""

    failures = 0
    for idx, row in df[df["deliverability_flag"] == "catch-all"].iterrows():
        if smtp_probe(row["email"]):
            df.at[idx, "deliverability_flag"] = "bounce-suspect"
            failures += 1
    df.attrs["smtp_failures"] = failures
    return df


@dataclass
class RosterEntry:
    name: str
    title: str
    email: str


@retry(wait=wait_fixed(2), stop=stop_after_attempt(3))
async def fetch_roster(page, school: str) -> Optional[str]:
    await page.goto(SEARCH_URL)
    await page.fill("input[type=search]", school)
    await page.wait_for_timeout(1000)
    links = page.locator("a[href^='/teams']")
    if await links.count() == 0:
        return None
    url = await links.first.get_attribute("href")
    return f"https://scoreboard.clippd.com{url}"


async def scrape_scoreboard_async(df: pd.DataFrame) -> Dict[str, Optional[str]]:
    """Return mapping of email -> team page URL."""

    results: Dict[str, Optional[str]] = {}

    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=True)
        page = await browser.new_page()
        for _, row in tqdm(df.iterrows(), total=len(df)):
            url = await fetch_roster(page, row["school"])
            results[row["email"]] = url
            await asyncio.sleep(1)
        await browser.close()
    return results


@retry(wait=wait_fixed(2), stop=stop_after_attempt(3))
def get_roster(url: str) -> List[RosterEntry]:
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    rows = []
    for tr in soup.select("table tr"):
        cols = [c.get_text(strip=True) for c in tr.select("td")]
        if len(cols) >= 3:
            rows.append(RosterEntry(name=cols[0], title=cols[1], email=parseaddr(cols[2])[1]))
    return rows


def fuzzy_match(df: pd.DataFrame, roster_dict: Dict[str, Optional[str]]) -> pd.DataFrame:
    """Add scoreboard match confidence and active flag."""

    confidences = []
    actives = []
    urls = []
    for _, row in tqdm(df.iterrows(), total=len(df)):
        email = row["email"]
        url = roster_dict.get(email)
        urls.append(url)
        if not url:
            confidences.append(0)
            actives.append(False)
            continue
        try:
            roster = get_roster(url)
        except Exception as exc:  # noqa: BLE001
            LOGGER.debug("Failed to fetch roster for %s: %s", url, exc)
            confidences.append(0)
            actives.append(False)
            continue
        best = 0
        active = False
        target_domain = email.split("@")[-1]
        for entry in roster:
            if "Head Coach" not in entry.title and "Assistant Coach" not in entry.title:
                continue
            domain = entry.email.split("@")[-1]
            if domain != target_domain:
                continue
            ratio = fuzz.ratio(row["name"], entry.name)
            best = max(best, ratio)
            if ratio >= 90:
                active = True
        confidences.append(best)
        actives.append(active)
    df["source_scoreboard_url"] = urls
    df["scoreboard_match_confidence"] = confidences
    df["is_active"] = actives
    return df


def export_results(df: pd.DataFrame, active_csv: Path, audit_json: Path) -> None:
    """Export final results and audit summary."""

    total_rows = len(df)
    email_in_valid_list = df[df["deliverability_flag"] != "invalid"].shape[0]
    still_active = df[df["is_active"]].shape[0]
    dropped_not_found = df[df["source_scoreboard_url"].isna()].shape[0]
    dropped_not_active = df[(~df["is_active"]) & df["source_scoreboard_url"].notna()].shape[0]
    smtp_failures = int(df.attrs.get("smtp_failures", 0))

    active_df = df[df["is_active"]].copy()
    active_df = active_df[
        [
            "school",
            "name",
            "gender",
            "title",
            "email",
            "phone",
            "division",
            "state",
            "source_scoreboard_url",
            "deliverability_flag",
            "scoreboard_match_confidence",
        ]
    ]
    active_df.drop_duplicates(subset=["email"], inplace=True)
    active_df.to_csv(active_csv, index=False)

    audit = {
        "total_rows": total_rows,
        "email_in_valid_list": email_in_valid_list,
        "still_active": still_active,
        "dropped_not_found": dropped_not_found,
        "dropped_not_active": dropped_not_active,
        "smtp_soft_bounce_failures": smtp_failures,
    }

    with open(audit_json, "w", encoding="utf-8") as fh:
        json.dump(audit, fh, indent=2)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Purge outdated coach contacts")
    parser.add_argument("--men-master", default="men_master.csv", type=Path)
    parser.add_argument("--women-master", default="women_master.csv", type=Path)
    parser.add_argument("--men-valid", default="men_valid.csv", type=Path)
    parser.add_argument("--women-valid", default="women_valid.csv", type=Path)
    parser.add_argument("--output-csv", default="active_coaches.csv", type=Path)
    parser.add_argument("--audit-json", default="audit.json", type=Path)
    parser.add_argument("--skip-smtp", action="store_true", help="Skip SMTP probe")
    return parser.parse_args()


if __name__ == "__main__":
    setup_logging()
    args = parse_args()

    df = load_data(args.men_master, args.women_master, args.men_valid, args.women_valid)
    if not args.skip_smtp:
        df = optional_smtp_probe(df)

    roster_urls = asyncio.run(scrape_scoreboard_async(df))
    df = fuzzy_match(df, roster_urls)
    export_results(df, args.output_csv, args.audit_json)

    LOGGER.info("Done")
