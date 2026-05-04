"""
메소 분배 디스코드 봇 (옛메 경매장 수수료 반영)

슬래시 명령:
    /분배 몇명:<int> 분배금:<int> [수수료율:<float, 기본 3.0>]

- 입력 '분배금' = 경매장 판매가 (수수료 차감 전)
- 수수료 = floor(분배금 × 수수료율 / 100)
- 실수령 = 분배금 - 수수료
- 1인당 = 실수령 // 몇명 (소수점 절사, 나머지는 별도 안내)
"""

import math
import os
import logging

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

# ── 설정 ──────────────────────────────────────────────────────────────
load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("meso-bot")

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)


# ── 라이프사이클 ──────────────────────────────────────────────────────
@bot.event
async def on_ready():
    try:
        synced = await bot.tree.sync()
        log.info("로그인 성공: %s (슬래시 명령어 %d개 동기화 완료)", bot.user, len(synced))
    except Exception as e:
        log.exception("슬래시 명령어 동기화 실패: %s", e)


# ── /분배 명령 ────────────────────────────────────────────────────────
@bot.tree.command(
    name="분배",
    description="경매장 판매가에서 수수료를 빼고 인원수로 나눠 1인당 받을 메소를 계산합니다.",
)
@app_commands.describe(
    몇명="분배받을 인원수 (1 이상)",
    분배금="경매장 판매가 — 수수료 차감 전 메소 (1 이상)",
    수수료율="경매장 수수료 (%) — 기본값 3, 수수료 없으면 0",
)
async def distribute(
    interaction: discord.Interaction,
    몇명: app_commands.Range[int, 1, 1_000_000],
    분배금: app_commands.Range[int, 1, 10_000_000_000_000],
    수수료율: app_commands.Range[float, 0.0, 100.0] = 3.0,
):
    fee = math.floor(분배금 * 수수료율 / 100)
    net = 분배금 - fee
    per_person = net // 몇명
    remainder = net - per_person * 몇명

    rate_str = f"{수수료율:g}%"  # 3 / 5 / 3.5 등 보기 좋게

    lines = [
        f"📦 경매장 판매가 : **{분배금:,}메소**",
        f"💸 수수료 ({rate_str}) : **-{fee:,}메소**",
        f"💵 실수령 : **{net:,}메소**",
        "",
        f"**{net:,}메소**를 **{몇명}명**으로 분배하면",
        f"## 1인당 {per_person:,}메소 입니다",
    ]
    if remainder:
        lines.append("")
        lines.append(f"_나머지 {remainder:,}메소는 버림 처리되었어요._")

    embed = discord.Embed(
        title="💰 메소 분배 결과",
        description="\n".join(lines),
        color=0xF1C40F,
    )
    embed.set_footer(text=f"요청자: {interaction.user.display_name}")

    await interaction.response.send_message(embed=embed)


# ── 엔트리포인트 ─────────────────────────────────────────────────────
if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError(
            "DISCORD_BOT_TOKEN 환경변수가 비어 있어요. .env 또는 호스팅 환경변수에 토큰을 등록해주세요."
        )
    bot.run(TOKEN)
