"""
메이플스토리 파티 분배 디스코드 봇
ConnectLabs · oh_nightmare · 2025

슬래시 명령:
    /분배 아이템명:<str> 판매금:<int> 파티원수:<int> [카르마가위:<int>]

처리 순서:
    1) 판매금에서 카르마의 가위 비용 차감
    2) 차감 후 금액을 파티원수로 균등 분배 (버림)
    3) 1인당 몫 기준으로 택배 수수료 계산
    4) 1인당 몫에서 택배 수수료 차감 → 최종 수령액
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


# ── 택배 수수료 구간 (송금액 하한, 수수료율) ─────────────────────────
# 높은 구간부터 검사하여 첫 매치를 사용한다.
PARCEL_FEE_BRACKETS: list[tuple[int, float]] = [
    (100_000_000, 0.06),  # 1억 이상      → 6.00%
    (25_000_000, 0.05),   # 2,500만 이상  → 5.00%
    (10_000_000, 0.04),   # 1,000만 이상  → 4.00%
    (5_000_000, 0.03),    # 500만 이상    → 3.00%
    (1_000_000, 0.018),   # 100만 이상    → 1.80%
    (100_000, 0.008),     # 10만 이상     → 0.80%
]
PARCEL_BASE_FEE = 10_000  # 택배 기본료


def calc_parcel_fee(amount: int) -> tuple[int, float]:
    """송금액 기준 택배 수수료 = 기본료 + (송금액 × 구간 수수료율).
    Returns: (수수료, 적용 수수료율)"""
    rate = 0.0
    for threshold, r in PARCEL_FEE_BRACKETS:
        if amount >= threshold:
            rate = r
            break
    fee = PARCEL_BASE_FEE + math.floor(amount * rate)
    return fee, rate


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
    description="메이플스토리 파티 판매금 분배 — 택배 수수료·카르마 가위 자동 차감",
)
@app_commands.describe(
    아이템명="판매한 아이템 이름",
    판매금="거래소 수수료 제외 후 실수령 메소",
    파티원수="분배할 파티 인원 (1~15)",
    카르마가위="카르마의 가위 구매 비용 (없으면 생략)",
)
async def distribute(
    interaction: discord.Interaction,
    아이템명: str,
    판매금: app_commands.Range[int, 1, 100_000_000_000],
    파티원수: app_commands.Range[int, 1, 15],
    카르마가위: app_commands.Range[int, 0, 1_000_000_000] = 0,
):
    # 1) 카르마 가위 차감
    after_karma = 판매금 - 카르마가위
    if after_karma <= 0:
        await interaction.response.send_message(
            f"⚠️ 카르마의 가위 비용(`{카르마가위:,}메소`)이 판매금(`{판매금:,}메소`) 이상이라 분배할 금액이 없어요.",
            ephemeral=True,
        )
        return

    # 2) 균등 분배 (버림)
    per_share = after_karma // 파티원수
    remainder = after_karma - per_share * 파티원수

    # 3) 택배 수수료 (1인당 몫 기준)
    parcel_fee, rate = calc_parcel_fee(per_share)
    rate_label = f"{rate * 100:g}%" if rate > 0 else "구간 미해당(0%)"

    # 4) 최종 수령액
    final_amount = per_share - parcel_fee

    # ── 임베드 구성 ──────────────────────────────────────────────────
    lines = [
        f"수수료 제외 **{after_karma:,}메소** 정산 · **{파티원수}명** 분배",
        "",
        "**📊 정산 내역**",
        f"판매금 (거래소 수수료 제외 후) : `{판매금:,}메소`",
    ]
    if 카르마가위 > 0:
        lines.append(f"카르마의 가위 : `-{카르마가위:,}메소`")
    lines.extend([
        "━━━━━━━━━━━━━━━━━━━",
        f"정산 금액 : `{after_karma:,}메소`",
        f"÷ {파티원수}명 → 1인당 몫 : `{per_share:,}메소`",
        f"택배 수수료 (기본료 {PARCEL_BASE_FEE:,} + {rate_label}) : `-{parcel_fee:,}메소`",
        "━━━━━━━━━━━━━━━━━━━",
        "",
        "💰 **최종 수령액 (택배 발송 금액)**",
        f"## 1인당 `{final_amount:,}` 메소",
    ])

    if remainder:
        lines.append(f"\n_나머지 {remainder:,}메소는 버림 처리되었어요._")

    if final_amount < 0:
        lines.append(
            f"\n⚠️ 1인당 몫이 택배 수수료보다 작아 최종 수령액이 음수입니다. 분배 방식을 다시 확인해주세요."
        )

    # 분배 내역 (2명 이상일 때만)
    if 파티원수 >= 2:
        lines.append("")
        lines.append("**📦 분배 내역**")
        for i in range(1, 파티원수 + 1):
            lines.append(f"• 파티원 {i} : `{final_amount:,}메소`")

    embed = discord.Embed(
        title=f"🍁 [ {아이템명} ] 판매 수익금 분배",
        description="\n".join(lines),
        color=0xE74C3C,
    )
    embed.set_footer(
        text=(
            f"택배 기본료 {PARCEL_BASE_FEE:,}메소 + 송금 구간별 수수료율 적용 "
            f"· 요청: {interaction.user.display_name}"
        )
    )

    await interaction.response.send_message(embed=embed)


# ── 엔트리포인트 ─────────────────────────────────────────────────────
if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError(
            "DISCORD_BOT_TOKEN 환경변수가 비어 있어요. .env 또는 호스팅 환경변수에 토큰을 등록해주세요."
        )
    bot.run(TOKEN)
