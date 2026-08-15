import asyncio
import csv
import os
from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Set, Tuple

import coc
from dotenv import load_dotenv

load_dotenv()
EMAIL = os.environ["EMAIL"]
PASSWORD = os.environ["PASSWORD"]
CLAN_TAG = os.getenv("CLAN_TAG")

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


def split_war_sides(war: coc.ClanWar) -> Tuple[coc.WarClan, coc.WarClan]:
    if war.clan.tag.replace("#", "") == CLAN_TAG.replace("#", ""):
        return war.clan, war.opponent
    if war.opponent.tag.replace("#", "") == CLAN_TAG.replace("#", ""):
        return war.opponent, war.clan
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


def collect_attack_rows(our_clan: coc.WarClan, opponent: coc.WarClan, war_start: str, run_date: str) -> List[AttackRow]:
    opponent_th: Dict[str, int] = {m.tag: m.town_hall for m in opponent.members}
    opponent_position: Dict[str, int] = {m.tag: m.map_position for m in opponent.members}
    our_position: Dict[str, int] = {m.tag: m.map_position for m in our_clan.members}

    all_attacks: List[Tuple[int, coc.ClanWarMember, coc.WarAttack]] = []
    for member in our_clan.members:
        for attack in member.attacks:
            all_attacks.append((attack.order, member, attack))
    all_attacks.sort(key=lambda x: x[0])

    best_stars_before: Dict[str, int] = {}
    attack_counters: Dict[str, int] = {}
    rows: List[AttackRow] = []

    for order, member, attack in all_attacks:
        defender_tag = attack.defender_tag
        prior_best = best_stars_before.get(defender_tag, 0)
        defender_th = opponent_th.get(defender_tag, 0)

        attack_counters[member.tag] = attack_counters.get(member.tag, 0) + 1

        rows.append(AttackRow(
            war_start=war_start,
            run_date=run_date,
            player_name=member.name,
            player_tag=member.tag,
            th_level=member.town_hall,
            attack_number=attack_counters[member.tag],
            stars=attack.stars,
            destruction=attack.destruction,
            defender_th=defender_th,
            position_diff=our_position.get(member.tag, 0) - opponent_position.get(defender_tag, 0),
            already_3_starred=prior_best == 3,
        ))

        best_stars_before[defender_tag] = max(prior_best, attack.stars)

    return rows


def collect_defense_rows(our_clan: coc.WarClan, opponent: coc.WarClan, war_start: str, run_date: str) -> List[DefenseRow]:
    our_members: Dict[str, coc.ClanWarMember] = {m.tag: m for m in our_clan.members}
    defense_counters: Dict[str, int] = {}
    rows: List[DefenseRow] = []

    for member in opponent.members:
        for attack in member.attacks:
            defender_tag = attack.defender_tag
            defender = our_members.get(defender_tag)
            if not defender:
                continue
            defense_counters[defender_tag] = defense_counters.get(defender_tag, 0) + 1
            rows.append(DefenseRow(
                war_start=war_start,
                run_date=run_date,
                player_name=defender.name,
                player_tag=defender_tag,
                th_level=defender.town_hall,
                defense_number=defense_counters[defender_tag],
                stars=attack.stars,
                destruction=attack.destruction,
                attacker_th=member.town_hall,
            ))

    return rows


def dataclass_to_row(obj) -> dict:
    return obj.__dict__


async def main() -> None:
    async with coc.Client(key_names="gh-actions-key") as client:
        try:
            await client.login(EMAIL, PASSWORD)
        except coc.InvalidCredentials as error:
            raise SystemExit(str(error))

        try:
            war = await client.get_current_war(CLAN_TAG)
        except coc.PrivateWarLog:
            print("War log is private")
            return

        if war is None or war.state not in ("inWar", "warEnded"):
            state = war.state if war else None
            print(f"War state is '{state}', skipping")
            return

        our_clan, opponent = split_war_sides(war)
        if not our_clan:
            print("Clan not found in current war data")
            return

        war_start = war.preparation_start_time.time.strftime("%Y-%m-%d")
        run_date = date.today().isoformat()

        attack_rows = collect_attack_rows(our_clan, opponent, war_start, run_date)
        defense_rows = collect_defense_rows(our_clan, opponent, war_start, run_date)

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
    asyncio.run(main())