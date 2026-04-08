"""
discord_sync.py — получает реакции с Discord-постов и обновляет fortune_wheel_save.json
"""

import asyncio
import json
import os
from pathlib import Path

import discord
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID"))
MESSAGE_IDS = [int(x.strip()) for x in os.getenv("DISCORD_MESSAGE_IDS", "").split(",") if x.strip()]

DATA_FILE = Path("fortune_wheel_save.json")

# Эмодзи которые полностью игнорируем (служебные — сюда не входит "tools")
IGNORED_EMOJI: set[str] = set()

# Расшифровка: имя эмодзи → красивое название игры
GAME_NAMES: dict[str, str] = {
    "Avalon":               "Tainted Grail: The Fall of Avalon",
    "Bioshock":             "BioShock 2",
    "CoD":                  "Call of Duty",
    "DarkMessiah":          "Dark Messiah of Might and Magic",
    "DarkSouls":            "Dark Souls Remastered DLC",
    "DeathStranding":       "Death Stranding",
    "Dispatch":             "Dispatch",
    "FarCry":               "Far Cry",
    "Frostpunk":            "Frostpunk",
    "GTA":                  "Grand Theft Auto",
    "HalfLife":             "Half-Life",
    "KCD":                  "Kingdom Come: Deliverance",
    "Lies_of_P":            "Lies of P",
    "MGS":                  "Metal Gear Solid",
    "Nioh":                 "Nioh",
    "TES":                  "The Elder Scrolls",
    "TloU":                 "The Last of Us",
    "Warhammer":            "Warhammer 40K: Rogue Trader",
    "Witcher":              "The Witcher",
    "battle_brothers":      "Battle Brothers",
    "borderlands":          "Borderlands",
    "ck3":                  "Crusader Kings III",
    "codevein":             "Code Vein",
    "crysis":               "Crysis",
    "dead_space":           "Dead Space",
    "dishonored":           "Dishonored",
    "dragonage":            "Dragon Age",
    "fable":                "Fable",
    "fear":                 "F.E.A.R. 2",
    "gothic":               "Gothic",
    "mafia":                "Mafia 2",
    "masseffect":           "Mass Effect 2",
    "minecraft":            "Minecraft",
    "nfs":                  "Need for Speed",
    "planet_alcatraz":      "Planet Alcatraz",
    "portal":               "Portal",
    "rag_doll_kung_fu":     "Rag Doll Kung Fu",
    "remnant":              "Remnant 2",
    "resident_evil":        "Resident Evil Zero",
    "sekiro":               "Sekiro: Shadows Die Twice",
    "total_war_warhammer3": "Total War: Warhammer III (Мастер смерти Сникч)",
    "vampyr":               "Vampyr",
    "wolfenstein":          "Wolfenstein",
    "xcom":                 "XCOM: Chimera Squad",
    "🛠️":                   "Прохождение дропнутой игры на мой выбор",
}


def load_existing_data() -> dict:
    if DATA_FILE.exists():
        try:
            return json.loads(DATA_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"next_lot_id": 1, "dark_mode": True, "lots": [], "history": []}


def save_data(data: dict) -> None:
    DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


async def fetch_reactions(progress_cb=None) -> list[dict]:
    """Читает реакции из Discord. progress_cb(message) — опциональный колбек для UI."""
    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)

    results: dict[str, float] = {}

    def _progress(msg: str):
        if progress_cb:
            progress_cb(msg)
        else:
            print(msg)

    @client.event
    async def on_ready():
        _progress(f"Подключён как {client.user}")
        try:
            channel = await client.fetch_channel(CHANNEL_ID)

            for i, msg_id in enumerate(MESSAGE_IDS):
                try:
                    message = await channel.fetch_message(msg_id)
                    _progress(f"Читаю пост {i + 1}/{len(MESSAGE_IDS)} ({len(message.reactions)} реакций)...")

                    for reaction in message.reactions:
                        emoji_str = str(reaction.emoji)
                        if emoji_str in IGNORED_EMOJI:
                            continue

                        key = reaction.emoji.name if isinstance(reaction.emoji, discord.Emoji) else emoji_str

                        # -1 за реакцию инициации (не запрашиваем список пользователей — быстрее)
                        count = max(0, reaction.count - 1)

                        if count > 0:
                            results[key] = results.get(key, 0) + count

                except discord.NotFound:
                    _progress(f"Сообщение {msg_id} не найдено")
                except discord.Forbidden:
                    _progress(f"Нет доступа к сообщению {msg_id}")

        except Exception as e:
            _progress(f"Ошибка: {e}")
        finally:
            await client.close()

    await client.start(TOKEN)

    lots = []
    for key, count in results.items():
        name = GAME_NAMES.get(key, key)
        lots.append({"name": name, "points": float(count)})
    # Сортируем по количеству голосов (убыв.) — для отображения в списке
    lots.sort(key=lambda x: x["points"], reverse=True)
    return lots


def build_lots_from_discord(fresh_lots: list[dict], existing_data: dict) -> tuple[list[dict], int]:
    """
    Полностью заменяет лоты из Discord.
    Eliminated-статус сохраняется для игр которые уже были.
    Ручные лоты (которых нет в Discord) — удаляются.
    """
    existing_by_name = {lot["name"].lower(): lot for lot in existing_data.get("lots", [])}
    next_id = max((lot["id"] for lot in existing_data.get("lots", [])), default=0) + 1

    updated = []
    for fresh in fresh_lots:
        name_lower = fresh["name"].lower()
        if name_lower in existing_by_name:
            old = existing_by_name[name_lower]
            updated.append({
                "id": old["id"],
                "name": fresh["name"],
                "points": fresh["points"],
                "eliminated": old.get("eliminated", False),
            })
        else:
            updated.append({
                "id": next_id,
                "name": fresh["name"],
                "points": fresh["points"],
                "eliminated": False,
            })
            next_id += 1

    return updated, next_id


async def sync(progress_cb=None) -> str:
    """
    Основная функция синхронизации.
    progress_cb(str) — опциональный колбек для отображения прогресса в UI.
    Возвращает итоговое сообщение.
    """
    def _p(msg):
        if progress_cb:
            progress_cb(msg)
        else:
            print(f"[Sync] {msg}")

    _p("Подключаюсь к Discord...")
    fresh_lots = await fetch_reactions(progress_cb=progress_cb)

    if not fresh_lots:
        msg = "Реакций не найдено — файл не изменён."
        _p(msg)
        return msg

    _p(f"Получено {len(fresh_lots)} игр. Сохраняю...")

    data = load_existing_data()
    merged, next_id = build_lots_from_discord(fresh_lots, data)
    data["lots"] = merged
    data["next_lot_id"] = next_id
    save_data(data)

    result = f"Готово! Загружено {len(fresh_lots)} игр из Discord."
    _p(result)
    return result


def main():
    if not TOKEN:
        print("Ошибка: DISCORD_TOKEN не найден в .env")
        return
    asyncio.run(sync())


if __name__ == "__main__":
    main()