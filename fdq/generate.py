"""Synthetic but realistic deliveries from three sources, with planted problems.

    provider A  (event data, JSON per match, Latin names, own IDs)
    provider B  (match + player stats, CSV, Cyrillic names, different IDs)
    GPS system  (our team only, CSV per day, "И. Петров" + shirt number)

Every planted problem is listed in data/raw/_manifest.json. The tests use the
manifest to prove that the data quality suite catches each of them, which is
how you test a test suite: plant known bugs and measure recall.

Real data is the next step (see docs/TASKS.md): the loaders only depend on the
file formats, so a StatsBomb open-data adapter can replace provider A.
"""

from __future__ import annotations

import csv
import json
import random
import shutil
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

FIRST_NAMES = {
    # Cyrillic -> how provider A romanizes it (deliberately not the same as our transliteration)
    "Алексей": "Aleksei", "Юрий": "Yuri", "Фёдор": "Fyodor", "Дмитрий": "Dmitri",
    "Андрей": "Andrei", "Сергей": "Sergei", "Николай": "Nikolai", "Евгений": "Evgeni",
    "Илья": "Ilya", "Максим": "Maxim", "Артём": "Artyom", "Кирилл": "Kirill",
    "Иван": "Ivan", "Павел": "Pavel", "Роман": "Roman", "Егор": "Egor",
    "Даниил": "Daniil", "Михаил": "Mikhail", "Глеб": "Gleb", "Тимур": "Timur",
}

SURNAMES = """Смирнов Иванов Кузнецов Соколов Попов Лебедев Козлов Новиков Морозов Петров
Волков Соловьёв Васильев Зайцев Павлов Семёнов Голубев Виноградов Богданов Воробьёв
Фёдоров Михайлов Беляев Тарасов Белов Комаров Орлов Киселёв Макаров Андреев Ковалёв
Ильин Гусев Титов Кузьмин Кудрявцев Баранов Куликов Алексеев Степанов Яковлев Сорокин
Сергеев Романов Захаров Борисов Королёв Герасимов Пономарёв Григорьев Лазарев Медведев
Ершов Никитин Соболев Рябов Поляков Цветков Данилов Жуков Фролов Журавлёв Николаев
Крылов Максимов Сидоров Осипов Белоусов Федотов Дорофеев Егоров Матвеев Бобров Дмитриев
Калинин Анисимов Петухов Антонов Тимофеев Никифоров Веселов Филиппов Марков Большаков
Суханов Миронов Ширяев Александров Коновалов Шестаков Казаков Ефимов Денисов Громов
Фомин Давыдов Мельников Щербаков Блинов Колесников Жуковский Вишневский""".split()

# Provider A's own romanization: ё -> yo, -ий -> -y, х -> kh, etc.
_A_ROMAN = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo", "ж": "zh", "з": "z",
    "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
    "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh",
    "щ": "shch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}

# (canonical name, provider A name) — must agree with reference/teams.csv
TEAMS = [
    ("Сокол", "FC Sokol"), ("Звезда", "FC Zvezda"), ("Метеор", "Meteor"),
    ("Волна", "FC Volna"), ("Энергия", "Energiya"), ("Рубеж", "Rubezh FC"),
]
OWN = 0  # index of our club in TEAMS


def romanize_a(surname: str) -> str:
    s = surname.lower()
    if s.endswith("ий"):
        s = s[:-2] + "y"
    out = "".join(_A_ROMAN.get(ch, ch) for ch in s)
    return out.capitalize()


@dataclass
class Player:
    a_id: int
    b_key: str
    first: str
    surname: str
    team: int
    jersey: int
    birth: date
    position: str  # GK / DF / MF / FW

    @property
    def name_a(self) -> str:
        return f"{FIRST_NAMES[self.first]} {romanize_a(self.surname)}"

    @property
    def name_b(self) -> str:
        return f"{self.surname} {self.first}"

    @property
    def name_gps(self) -> str:
        return f"{self.first[0]}. {self.surname}"


@dataclass
class World:
    players: list[Player] = field(default_factory=list)
    issues: list[dict] = field(default_factory=list)


def _squad(rng: random.Random, team: int, size: int, start_id: int, surnames: list[str]) -> list[Player]:
    positions = ["GK"] * 2 + ["DF"] * 6 + ["MF"] * 6 + ["FW"] * (size - 14)
    jerseys = rng.sample(range(1, 40), size)
    out = []
    for i in range(size):
        out.append(Player(
            a_id=start_id + i,
            b_key=f"SH-P{start_id + i + 7000}",
            first=rng.choice(list(FIRST_NAMES)),
            surname=surnames.pop(),
            team=team,
            jersey=jerseys[i],
            birth=date(1993, 1, 1) + timedelta(days=rng.randint(0, 13 * 365)),
            position=positions[i],
        ))
    return out


def _lineup(rng: random.Random, squad: list[Player]) -> list[tuple[Player, int]]:
    """11 starters + 3 substitutes with minutes; one goalkeeper starts."""
    gks = [p for p in squad if p.position == "GK"]
    outfield = [p for p in squad if p.position != "GK"]
    rng.shuffle(outfield)
    starters = [gks[0]] + outfield[:10]
    subs = outfield[10:13]
    result = [(p, 90) for p in starters]
    for i, sub in enumerate(subs):
        on = rng.randint(55, 80)
        idx = 1 + rng.randrange(10)
        off_player, _ = result[idx]
        if result[idx][1] == 90:
            result[idx] = (off_player, on)
            result.append((sub, 90 - on))
    return result


def generate(out_dir: Path, seed: int = 42, n_matches: int = 10) -> dict:
    rng = random.Random(seed)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    (out_dir / "provider_a").mkdir(parents=True)
    (out_dir / "provider_b").mkdir(parents=True)
    (out_dir / "gps").mkdir(parents=True)

    world = World()
    surnames = SURNAMES.copy()
    rng.shuffle(surnames)
    squads = {OWN: _squad(rng, OWN, 18, 100, surnames)}
    for t in range(1, len(TEAMS)):
        squads[t] = _squad(rng, t, 14, 100 + t * 100, surnames)
    for s in squads.values():
        world.players.extend(s)

    first_match = date(2026, 8, 1)
    fixtures = []
    opponents = list(range(1, len(TEAMS)))
    for i in range(n_matches):
        opp = opponents[i % len(opponents)]
        home = i % 2 == 0
        fixtures.append((first_match + timedelta(days=7 * i), (OWN, opp) if home else (opp, OWN)))

    matches = []  # rich per-match records used to write all deliveries
    for i, (day, (home, away)) in enumerate(fixtures):
        a_id, b_id = f"A-{1001 + i}", f"SH-{5501 + i}"
        lineups = {home: _lineup(rng, squads[home]), away: _lineup(rng, squads[away])}
        events = []
        used = set()  # genuine events never share (player, minute, second, type): only retries do
        n = 0
        for team, lineup in lineups.items():
            for p, minutes in lineup:
                if minutes <= 0:
                    continue
                start = 0 if minutes == 90 or (p, minutes) in lineup[:11] else 90 - minutes
                end = start + minutes
                n_passes = int(minutes / 90 * rng.uniform(15, 55))
                shot_rate = {"GK": 0, "DF": 0.4, "MF": 1.0, "FW": 2.5}[p.position]
                n_shots = sum(rng.random() < shot_rate * minutes / 90 / 3 for _ in range(3))
                kinds = (["pass"] * n_passes + ["shot"] * n_shots
                         + ["tackle"] * rng.randint(0, 3) + ["foul"] * rng.randint(0, 2))
                for kind in kinds:
                    minute = rng.randint(start, max(start, end - 1))
                    second = rng.randint(0, 59)
                    while (p.a_id, minute, second, kind) in used:
                        minute, second = rng.randint(start, max(start, end - 1)), rng.randint(0, 59)
                    used.add((p.a_id, minute, second, kind))
                    outcome, xg = None, None
                    if kind == "pass":
                        outcome = "complete" if rng.random() < 0.82 else "incomplete"
                    elif kind == "shot":
                        # Real shot xG is skewed: most shots are poor chances (mean ~0.1).
                        xg = round(min(0.85, max(0.01, rng.betavariate(1.2, 9))), 3)
                        outcome = "goal" if rng.random() < xg else rng.choice(["saved", "off_target", "blocked"])
                    elif kind == "tackle":
                        outcome = rng.choice(["won", "lost"])
                    n += 1
                    events.append({
                        "event_id": f"{a_id}-{n:05d}", "period": 1 if minute < 45 else 2,
                        "minute": minute, "second": second, "type": kind,
                        "team": TEAMS[team][1], "player_id": p.a_id, "outcome": outcome, "xg": xg,
                    })
        events.sort(key=lambda e: (e["minute"], e["second"]))
        goals = {t: sum(1 for e in events if e["team"] == TEAMS[t][1] and e["type"] == "shot" and e["outcome"] == "goal") for t in (home, away)}
        shots = {t: sum(1 for e in events if e["team"] == TEAMS[t][1] and e["type"] == "shot") for t in (home, away)}
        matches.append({"day": day, "home": home, "away": away, "a_id": a_id, "b_id": b_id,
                        "lineups": lineups, "events": events, "goals": goals, "shots": shots})

    # Not planted, but real: squad members who never got a minute exist in GPS and in
    # the club, yet not in the match provider that we use as the master list.
    played = {p.a_id for m in matches for p, mins in m["lineups"].get(OWN, []) if mins > 0}
    for p in squads[OWN]:
        if p.a_id not in played:
            world.issues.append({"issue": "squad_player_never_played", "player_a_id": p.a_id, "gps_name": p.name_gps})

    _plant_event_issues(rng, matches, world)
    for m in matches:
        _write_provider_a(out_dir, m)
    _write_provider_b(rng, out_dir, matches, world, squads)
    as_of = _write_gps(rng, out_dir, matches, world, squads[OWN])

    manifest = {"seed": seed, "as_of": as_of.isoformat(), "issues": world.issues}
    (out_dir / "_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=str))
    return manifest


def _plant_event_issues(rng: random.Random, matches: list[dict], world: World) -> None:
    # Delivery retry: 5 events sent twice under new IDs.
    m = matches[2]
    for e in rng.sample(m["events"], 5):
        dup = dict(e, event_id=e["event_id"] + "-r")
        m["events"].append(dup)
    world.issues.append({"issue": "duplicate_events", "match": m["a_id"], "count": 5})

    # Events without a player (provider glitch).
    m = matches[4]
    for e in rng.sample([e for e in m["events"] if e["type"] == "pass"], 4):
        e["player_id"] = None
    world.issues.append({"issue": "events_missing_player", "match": m["a_id"], "count": 4})

    # Impossible values.
    m = matches[1]
    shot = next(e for e in m["events"] if e["type"] == "shot" and e["outcome"] != "goal")
    shot["xg"] = 1.35
    world.issues.append({"issue": "xg_out_of_range", "match": m["a_id"], "event": shot["event_id"]})
    ev = next(e for e in m["events"] if e["type"] == "pass")
    ev["minute"] = 135
    world.issues.append({"issue": "minute_out_of_range", "match": m["a_id"], "event": ev["event_id"]})


def _write_provider_a(out_dir: Path, m: dict) -> None:
    lineups = [
        {"player_id": p.a_id, "name": p.name_a, "team": TEAMS[t][1], "jersey": p.jersey, "minutes": mins}
        for t, lineup in m["lineups"].items() for p, mins in lineup
    ]
    payload = {
        "match": {"match_id": m["a_id"], "date": m["day"].isoformat(),
                  "home_team": TEAMS[m["home"]][1], "away_team": TEAMS[m["away"]][1]},
        "lineups": lineups,
        "events": m["events"],
    }
    (out_dir / "provider_a" / f"{m['a_id']}.json").write_text(json.dumps(payload, ensure_ascii=False))


def _write_provider_b(rng: random.Random, out_dir: Path, matches: list[dict], world: World,
                      squads: dict[int, list[Player]]) -> None:
    own = squads[OWN]
    typo_player, renumbered_player = own[5], own[8]
    world.issues.append({"issue": "name_typo", "player_a_id": typo_player.a_id, "b_key": typo_player.b_key})
    world.issues.append({"issue": "jersey_changed", "player_a_id": renumbered_player.a_id, "b_key": renumbered_player.b_key})

    for i, m in enumerate(matches):
        if i == len(matches) - 1:
            world.issues.append({"issue": "match_missing_in_b", "match": m["a_id"]})
            continue  # late delivery: provider B has not sent the last match yet
        home_goals = m["goals"][m["home"]]
        if i == 5:
            home_goals += 1
            world.issues.append({"issue": "score_mismatch", "match": m["a_id"]})
        with open(out_dir / "provider_b" / f"matches_{m['day'].isoformat()}.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["match_id", "date", "home_team", "away_team", "home_goals", "away_goals", "home_shots", "away_shots"])
            # B counts blocked shots too -> its shot totals run a little higher (definition difference).
            w.writerow([m["b_id"], m["day"].isoformat(), TEAMS[m["home"]][0], TEAMS[m["away"]][0], home_goals,
                        m["goals"][m["away"]], m["shots"][m["home"]] + rng.randint(0, 2), m["shots"][m["away"]] + rng.randint(0, 2)])

        with open(out_dir / "provider_b" / f"players_{m['day'].isoformat()}.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["match_id", "player_key", "full_name", "birth_date", "team", "jersey", "minutes", "goals", "shots"])
            true_events = [e for e in m["events"] if not e["event_id"].endswith("-r")]  # B never saw A's retries
            for t, lineup in m["lineups"].items():
                for p, mins in lineup:
                    pid = p.a_id
                    goals = sum(1 for e in true_events if e["player_id"] == pid and e["type"] == "shot" and e["outcome"] == "goal")
                    shots = sum(1 for e in true_events if e["player_id"] == pid and e["type"] == "shot")
                    name = p.name_b
                    jersey = p.jersey
                    if p is typo_player:
                        name = name.replace(p.surname, p.surname[:-2] + p.surname[-1])  # "Петров" -> "Петрв"
                    if p is renumbered_player:
                        jersey = 77  # new shirt number not yet known to provider A
                    minutes = mins + (rng.choice([-1, 1]) if rng.random() < 0.2 else 0)  # rounding differences
                    w.writerow([m["b_id"], p.b_key, name, p.birth.isoformat(), TEAMS[t][0], jersey, minutes, goals, shots])
            if i == len(matches) - 2:
                # An academy player called up for one match: exists only in provider B.
                w.writerow([m["b_id"], "SH-P9999", "Новенький Арсений", "2008-03-14", TEAMS[OWN][0], 61, 6, 0, 0])
                world.issues.append({"issue": "unmatched_player", "b_key": "SH-P9999"})


def _write_gps(rng: random.Random, out_dir: Path, matches: list[dict], world: World, squad: list[Player]) -> date:
    match_days = {m["day"]: m for m in matches}
    rest_days = {d + timedelta(days=1) for d in match_days}
    start = min(match_days) - timedelta(days=28)  # pre-season gives the chronic window
    as_of = max(match_days) + timedelta(days=1)

    missing_day = matches[3]["day"]
    missing_player = next(p for p, mins in matches[3]["lineups"][OWN] if mins == 90 and p.position != "GK")
    world.issues.append({"issue": "gps_missing_for_match", "day": missing_day.isoformat(), "player_a_id": missing_player.a_id})

    anomaly_day = matches[6]["day"] - timedelta(days=3)
    anomaly_player = squad[3]
    world.issues.append({"issue": "gps_distance_anomaly", "day": anomaly_day.isoformat(), "player_a_id": anomaly_player.a_id})

    # A player misses two pre-season weeks (injury) and returns straight to full training:
    # the classic load spike that ACWR is meant to catch (see docs/metrics.md).
    injured = squad[10]
    injury_days = {start + timedelta(days=d) for d in range(7, 21)}
    world.issues.append({"issue": "return_from_injury_load_spike", "player_a_id": injured.a_id,
                         "absent_from": min(injury_days).isoformat(), "absent_to": max(injury_days).isoformat()})

    planted_speed = planted_dropout = planted_dup = False
    day = start
    while day <= as_of:
        rows = []
        if day in match_days:
            m = match_days[day]
            for p, mins in m["lineups"][OWN]:
                if mins <= 0 or (day == missing_day and p is missing_player):
                    continue
                dist = mins * rng.uniform(105, 125)
                rows.append(["match", p, mins + 5, dist, dist * rng.uniform(0.06, 0.09), rng.randint(8, 30), rng.uniform(28, 34)])
        elif day not in rest_days and day.weekday() != 6:
            for p in squad:
                if p is injured and day in injury_days:
                    continue
                dur = rng.uniform(60, 95)
                dist = dur * rng.uniform(60, 85)
                if day == anomaly_day and p is anomaly_player:
                    dist *= 3.2
                rows.append(["training", p, dur, dist, dist * rng.uniform(0.03, 0.07), rng.randint(3, 15), rng.uniform(24, 31)])

        if rows:
            if not planted_speed and day >= start + timedelta(days=10):
                rows[0][6] = 52.4  # sensor glitch: faster than any human
                world.issues.append({"issue": "gps_impossible_speed", "day": day.isoformat()})
                planted_speed = True
            if not planted_dropout and day in match_days and day > min(match_days):
                rows[1][3] = 0.0  # unit ran out of battery: 95 min, 0 m
                rows[1][4] = 0.0
                world.issues.append({"issue": "gps_dropout", "day": day.isoformat()})
                planted_dropout = True
            if not planted_dup and day >= start + timedelta(days=20):
                rows.append(list(rows[2]))  # same session exported twice
                world.issues.append({"issue": "gps_duplicate", "day": day.isoformat()})
                planted_dup = True
            with open(out_dir / "gps" / f"gps_{day.isoformat()}.csv", "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["session_date", "session_type", "athlete", "jersey", "duration_min",
                            "total_distance_m", "hsr_m", "sprints", "max_speed_kmh"])
                for kind, p, dur, dist, hsr, sprints, vmax in rows:
                    w.writerow([day.isoformat(), kind, p.name_gps, p.jersey, f"{dur:.1f}",
                                f"{dist:.0f}", f"{hsr:.0f}", sprints, f"{vmax:.1f}"])
        day += timedelta(days=1)
    return as_of
