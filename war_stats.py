import csv
import os
from dataclasses import dataclass
from datetime import date, datetime
import requests
from typing import Dict, List, Set, Tuple
from dotenv import load_dotenv

load_dotenv()
API_TOKEN = os.getenv("TOKEN")
CLAN_TAG = os.getenv("CLAN_TAG").replace("#", "")

API_URL = "https://api.clashofclans.com/v1/"
BASE_HEADERS = {"Authorization": f"Bearer {API_TOKEN}"}

ATTACKS_FILE = "war_attacks.csv"
DEFENSES_FILE = "war_defenses.csv"

ATTACKS_HEADERS = [
    "war_start",
    "run_date",
    "player_name",
    "player_tag",
    "th_level",
    "attack_number",
    "stars",
    "destruction",
    "defender_th",
    "position_diff",
    "already_3_starred",
]

DEFENSES_HEADERS = [
    "war_start",
    "run_date",
    "player_name",
    "player_tag",
    "th_level",
    "defense_number",
    "stars",
    "destruction",
    "attacker_th",
]


@dataclass
class AttackRow:
    war_start: str
    run_date: str
    player_name: str
    player_tag: str
    th_level: int
    attack_number: int
    stars: int
    destruction: float
    defender_th: int
    position_diff: int
    already_3_starred: bool


@dataclass
class DefenseRow:
    war_start: str
    run_date: str
    player_name: str
    player_tag: str
    th_level: int
    defense_number: int
    stars: int
    destruction: float
    attacker_th: int


def get(url: str) -> dict:
    response = requests.get(url, headers=BASE_HEADERS)
    response.raise_for_status()
    return response.json()


def get_current_war() -> dict:
    return get(f"{API_URL}clans/%23{CLAN_TAG}/currentwar")


def split_war_sides(war: dict) -> Tuple[dict, dict]:
    for side in ["clan", "opponent"]:
        if war[side].get("tag", "").replace("#", "") == CLAN_TAG:
            other_side = "opponent" if side == "clan" else "clan"
            return war[side], war[other_side]
    return None, None


def load_existing_keys(path: str, key_fields: Tuple[str, ...]) -> Set[tuple]:
    if not os.path.exists(path):
        return set()
    keys = set()
    with open(path, "r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            keys.add(tuple(row[field] for field in key_fields))
    return keys


def append_rows(path: str, headers: List[str], rows: List[dict]) -> None:
    file_exists = os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=headers, delimiter=";")
        if not file_exists:
            writer.writeheader()
        writer.writerows(rows)


def collect_attack_rows(war: dict, our_clan: dict, opponent: dict, war_start: str, run_date: str) -> List[AttackRow]:
    opponent_th: Dict[str, int] = {m["tag"]: m["townhallLevel"] for m in opponent.get("members", [])}
    opponent_position: Dict[str, int] = {m["tag"]: m["mapPosition"] for m in opponent.get("members", [])}
    our_position: Dict[str, int] = {m["tag"]: m["mapPosition"] for m in our_clan.get("members", [])}

    all_attacks: List[Tuple[int, dict, dict]] = []
    for member in our_clan.get("members", []):
        for attack in member.get("attacks", []):
            all_attacks.append((attack["order"], member, attack))
    all_attacks.sort(key=lambda x: x[0])

    best_stars_before: Dict[str, int] = {}
    attack_counters: Dict[str, int] = {}
    rows: List[AttackRow] = []

    for order, member, attack in all_attacks:
        defender_tag = attack["defenderTag"]
        prior_best = best_stars_before.get(defender_tag, 0)
        defender_th = opponent_th.get(defender_tag, 0)

        attack_counters[member["tag"]] = attack_counters.get(member["tag"], 0) + 1

        rows.append(AttackRow(
            war_start=war_start,
            run_date=run_date,
            player_name=member["name"],
            player_tag=member["tag"],
            th_level=member["townhallLevel"],
            attack_number=attack_counters[member["tag"]],
            stars=attack["stars"],
            destruction=attack.get("destructionPercentage", 0),
            defender_th=defender_th,
            position_diff=our_position.get(member["tag"], 0) - opponent_position.get(defender_tag, 0),
            already_3_starred=prior_best == 3,
        ))

        best_stars_before[defender_tag] = max(prior_best, attack["stars"])

    return rows


def collect_defense_rows(war: dict, our_clan: dict, opponent: dict, war_start: str, run_date: str) -> List[DefenseRow]:
    our_members: Dict[str, dict] = {m["tag"]: m for m in our_clan.get("members", [])}
    defense_counters: Dict[str, int] = {}
    rows: List[DefenseRow] = []

    for member in opponent.get("members", []):
        for attack in member.get("attacks", []):
            defender_tag = attack["defenderTag"]
            defender = our_members.get(defender_tag)
            if not defender:
                continue
            defense_counters[defender_tag] = defense_counters.get(defender_tag, 0) + 1
            rows.append(DefenseRow(
                war_start=war_start,
                run_date=run_date,
                player_name=defender["name"],
                player_tag=defender_tag,
                th_level=defender["townhallLevel"],
                defense_number=defense_counters[defender_tag],
                stars=attack["stars"],
                destruction=attack.get("destructionPercentage", 0),
                attacker_th=member["townhallLevel"],
            ))

    return rows


def format_war_start(raw: str) -> str:
    dt = datetime.strptime(raw, "%Y%m%dT%H%M%S.%fZ")
    return dt.strftime("%Y-%m-%d")


def dataclass_to_row(obj) -> dict:
    return obj.__dict__


def main() -> None:
    war = get_current_war()
    if war.get("state") not in ("inWar", "warEnded"):
        print(f"War state is '{war.get('state')}', skipping")
        return

    our_clan, opponent = split_war_sides(war)
    if not our_clan:
        print("Clan not found in current war data")
        return

    war_start = format_war_start(war.get("preparationStartTime", war.get("startTime", "")))
    run_date = date.today().isoformat()

    attack_rows = collect_attack_rows(war, our_clan, opponent, war_start, run_date)
    defense_rows = collect_defense_rows(war, our_clan, opponent, war_start, run_date)

    existing_attack_keys = load_existing_keys(ATTACKS_FILE, ("war_start", "player_tag", "attack_number"))
    existing_defense_keys = load_existing_keys(DEFENSES_FILE, ("war_start", "player_tag", "defense_number"))

    new_attack_rows = [
        r for r in attack_rows
        if (r.war_start, r.player_tag, str(r.attack_number)) not in existing_attack_keys
    ]
    new_defense_rows = [
        r for r in defense_rows
        if (r.war_start, r.player_tag, str(r.defense_number)) not in existing_defense_keys
    ]

    if new_attack_rows:
        append_rows(ATTACKS_FILE, ATTACKS_HEADERS, [dataclass_to_row(r) for r in new_attack_rows])
        print(f"Added {len(new_attack_rows)} attack rows")
    else:
        print("No new attacks")

    if new_defense_rows:
        append_rows(DEFENSES_FILE, DEFENSES_HEADERS, [dataclass_to_row(r) for r in new_defense_rows])
        print(f"Added {len(new_defense_rows)} defense rows")
    else:
        print("No new defenses")


if __name__ == "__main__":
    main()