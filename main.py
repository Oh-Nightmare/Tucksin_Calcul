"""
메이플스토리 파티 분배 디스코드 봇
ConnectLabs · oh_nightmare · 2025

택배 수수료 = 기본료 10,000 + Σ(구간 초과분 × 구간 요율) — 누진 방식

구간별 요율
    0       ~ 10만       : 0%
    10만    ~ 100만      : 0.8%
    100만   ~ 500만      : 1.8%
    500만   ~ 1,000만    : 3.0%
    1,000만 ~ 2,500만    : 4.0%
    2,500만 ~ 1억        : 5.0%
    1억 초과             : 6.0%

처리 순서 (/분배)
    1) 판매금 − 카르마의 가위 = 정산 금액
    2) 정산 금액 ÷ 파티원수 (버림) = 1인당 몫
    3) 1인당 몫 → 누진 택배 수수료 산출 (구간 누진 내역 표시)
    4) 1인당 몫 − 택배 수수료 = 최종 수령액
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


# ── 누진 구간 정의 (구간 하한, 구간 상한 또는 None, 요율 천분율, 라벨) ─
# 요율은 천분율(per-mille) 정수로 보관하여 부동소수점 오차를 차단한다.
# 8 = 0.8%, 18 = 1.8%, 30 = 3.0%, 40 = 4.0%, 50 = 5.0%, 60 = 6.0%
PROGRESSIVE_BRACKETS: list[tuple[int, int | None, int, str]] = [
    (100_000,      1_000_000,    8,  "10만 ~ 100만"),
    (1_000_000,    5_000_000,    18, "100만 ~ 500만"),
    (5_000_000,    10_000_000,   30, "500만 ~ 1,000만"),
    (10_000_000,   25_000_000,   40, "1,000만 ~ 2,500만"),
    (25_000_000,   100_000_000,  50, "2,500만 ~ 1억"),
    (100_000_000,  None,         60, "1억 초과"),
]
PARCEL_BASE_FEE = 10_000


def calc_parcel_fee(amount: int):
    """누진 택배 수수료 계산 (정수 산술).

    Returns:
        (총수수료, breakdown) — breakdown은 [(라벨, 구간내금액, 요율%, 부분수수료), ...]
    """
    breakdown: list[tuple[str, int, float, int]] = []
    progressive_sum = 0
    for low, high, rate_pm, label in PROGRESSIVE_BRACKETS:
        if amount <= low:
            break
        upper = min(amount, high) if high is not None else amount
        bracket_amount = upper - low
        bracket_fee = bracket_amount * rate_pm // 1000  # 정수 나눗셈 (floor)
        progressive_sum += bracket_fee
        breakdown.append((label, bracket_amount, rate_pm / 10, bracket_fee))
    total = PARCEL_BASE_FEE + progressive_sum
    return total, breakdown


def find_optimal_split(amount: int, max_n: int = 10):
    """1인당 몫을 N회로 분할 송금했을 때의 최적 횟수 탐색.
    탐색은 수수료가 증가하기 시작하면 즉시 중단(스펙 5장).

    Returns: (best_n, best_total_fee, single_fee)
    """
    single_fee, _ = calc_parcel_fee(amount)
    best_n, best_fee = 1, single_fee
    for n in range(2, max_n + 1):
        per = amount // n
        if per <= 0:
            break
        last = amount - per * (n - 1)  # 마지막 송금은 나머지를 흡수
        per_fee, _ = calc_parcel_fee(per)
        last_fee, _ = calc_parcel_fee(last)
        total = per_fee * (n - 1) + last_fee
        if total < best_fee:
            best_n, best_fee = n, total
        else:
            break
    return best_n, best_fee, single_fee


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
    description="메이플 파티 판매금 분배 — 누진 택배 수수료·카르마 가위 자동 차감",
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

    # 3) 누진 택배 수수료
    parcel_fee, breakdown = calc_parcel_fee(per_share)

    # 4) 최종 수령액
    final_amount = per_share - parcel_fee

    # 5) 분할 송금 절약 탐색
    best_n, best_fee, single_fee = find_optimal_split(per_share)
    save_amount = single_fee - best_fee

    # ── 임베드 본문 ──────────────────────────────────────────────────
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
        "",
        f"**🚚 택배 수수료 산출** (1인당 몫 `{per_share:,}메소` 기준 · 누진)",
    ])
    if breakdown:
        for label, bracket_amount, rate_pct, bracket_fee in breakdown:
            lines.append(
                f"• `{label}` : {bracket_amount:,} × {rate_pct:g}% = `{bracket_fee:,}메소`"
            )
    else:
        lines.append("• `10만 메소 미만` 구간 → 누진 수수료 0")
    lines.append(f"• `기본료` : `{PARCEL_BASE_FEE:,}메소`")
    lines.extend([
        "━━━━━━━━━━━━━━━━━━━",
        "",
        "**📤 1인당 송금 명세**",
        f"• 발송 원금 (1인당 몫) : `{per_share:,}메소`",
        f"• 수수료 적용 금액 : `-{parcel_fee:,}메소`",
        f"• 정상 발송 금액 : `{final_amount:,}메소`",
        "",
        "💰 **1인당 최종 수령액**",
        f"## `{final_amount:,}` 메소",
    ])

    if remainder:
        lines.append(f"\n_분배 시 나머지 {remainder:,}메소는 버림 처리되었어요._")

    if final_amount < 0:
        lines.append(
            f"\n⚠️ 1인당 몫이 택배 수수료보다 작아 최종 수령액이 음수입니다."
        )

    # 분할 송금 절약 팁 (절약액 > 0일 때만)
    if best_n > 1 and save_amount > 0:
        lines.append("")
        lines.append(
            f"💡 **절약 팁** : 1인당 몫을 **{best_n}회 분할 송금**하면 "
            f"수수료 `{best_fee:,}메소` "
            f"(단일 `{single_fee:,}` → **`{save_amount:,}메소 절약`**)"
        )

    # 분배 내역 (2명 이상)
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
            f"택배 기본료 {PARCEL_BASE_FEE:,}메소 + 송금 구간별 누진 수수료 적용 "
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
