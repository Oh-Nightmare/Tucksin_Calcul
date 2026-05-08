"""
메이플스토리 파티 분배 디스코드 봇
ConnectLabs · oh_nightmare · 2025

방식: 역산 (reverse calculation)
    분배자(=명령 실행자)가 1인당 정확히 P = (정산금액) / 파티원수 메소만큼 지출하도록
    송금 금액 S 를 역산. S + fee(S) ≈ P 가 성립.

택배 수수료 (누진)
    총 수수료 = 10,000 + Σ(구간 초과분 × 구간 요율)

처리 순서 (/분배)
    1) 판매금 − 카르마의 가위 = 정산 금액 (X)
    2) X ÷ 파티원수 (버림) = 1인당 분배금 (P)
    3) 분배자: P 본인 인벤토리에 보관 (택배 X · 수수료 X)
    4) 다른 파티원 (n-1명) : 각자 S 메소 수령
       — S = (P + C) / (1 + r) 후 정수 보정으로 산출
       — 분배자 1건당 지출 = S + fee(S) = P 이 되도록 함
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


# ── 누진 수수료 구간 (수수료 계산용) ─────────────────────────────────
# (구간 하한, 구간 상한 또는 None, 요율 천분율, 라벨)
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
    Returns: (총수수료, [(라벨, 구간내금액, 요율%, 부분수수료), ...])
    """
    breakdown: list[tuple[str, int, float, int]] = []
    progressive_sum = 0
    for low, high, rate_pm, label in PROGRESSIVE_BRACKETS:
        if amount <= low:
            break
        upper = min(amount, high) if high is not None else amount
        bracket_amount = upper - low
        bracket_fee = bracket_amount * rate_pm // 1000
        progressive_sum += bracket_fee
        breakdown.append((label, bracket_amount, rate_pm / 10, bracket_fee))
    total = PARCEL_BASE_FEE + progressive_sum
    return total, breakdown


# ── 역산용 구간 (P 상한, r 천분율, C 보정상수, 라벨) ─────────────────
# S = (P + C) / (1 + r). 구간 판별은 P 기준.
RECIPROCAL_BRACKETS: list[tuple[int | None, int, int, str]] = [
    (110_000,        0,    -10_000,    "P ≤ 11만"),
    (1_017_200,      8,    -9_200,     "11만 < P ≤ 1,017,200"),
    (5_089_200,      18,    800,        "1,017,200 < P ≤ 5,089,200"),
    (10_239_200,     30,    60_800,     "5,089,200 < P ≤ 10,239,200"),
    (25_839_200,     40,    160_800,    "10,239,200 < P ≤ 25,839,200"),
    (104_589_200,    50,    410_800,    "25,839,200 < P ≤ 104,589,200"),
    (None,           60,    1_410_800,  "P > 104,589,200 (1억 초과)"),
]


def calc_send_amount(P: int):
    """역산: 받는 사람이 P 메소를 받도록 (분배자 1건당 P 지출하도록)
    송금 금액 S 산출. 정수 보정으로 S + fee(S) >= P 보장.

    Returns: (S, r_pct, C, bracket_label)
    """
    r_pm = 0
    c = 0
    label = ""
    for upper, _r_pm, _c, _label in RECIPROCAL_BRACKETS:
        if upper is None or P <= upper:
            r_pm, c, label = _r_pm, _c, _label
            break

    # 초기 S: floor((P + C) × 1000 / (1000 + r_pm))
    if r_pm == 0:
        S = max(0, P + c)
    else:
        S = (P + c) * 1000 // (1000 + r_pm)
        if S < 0:
            S = 0

    # 정수 보정: S + fee(S) >= P 가 될 때까지
    fee, _ = calc_parcel_fee(S)
    while S + fee < P:
        S += 1
        fee, _ = calc_parcel_fee(S)

    return S, r_pm / 10, c, label


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
    description="메이플 파티 판매금 분배 (역산 방식) — 받는 사람 수령액·송금 금액 자동 계산",
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

    # 2) 1인당 분배금 P (균등 · 버림)
    P = after_karma // 파티원수
    remainder = after_karma - P * 파티원수
    n_receivers = 파티원수 - 1

    # 송금 불가 케이스 (P가 너무 작아 기본료조차 못 냄)
    if n_receivers >= 1 and P <= 10_000:
        await interaction.response.send_message(
            f"⚠️ 1인당 분배금(`{P:,}메소`)이 택배 기본료(10,000메소) 이하라 송금이 불가능해요. "
            f"인원수를 줄이거나 분배 방식을 재검토해주세요.",
            ephemeral=True,
        )
        return

    distributor_name = interaction.user.display_name

    # 3) 역산 (n_receivers ≥ 1 일 때만)
    if n_receivers == 0:
        S = P
        fee_per_send = 0
        r_pct = 0
        C = 0
        bracket_label = ""
        breakdown: list[tuple[str, int, float, int]] = []
        total_fees = 0
    else:
        S, r_pct, C, bracket_label = calc_send_amount(P)
        fee_per_send = P - S  # = fee(S) (정수 보정 후 동일)
        _, breakdown = calc_parcel_fee(S)
        total_fees = fee_per_send * n_receivers

    distributor_amount = P
    receiver_amount = S
    total_distributor_spend = P * 파티원수  # = after_karma (remainder 미포함)

    # ── 임베드 빌드 ──────────────────────────────────────────────────
    lines = [
        f"수수료 제외 **{after_karma:,}메소** 정산 · **{파티원수}명** 분배 _(역산 방식)_",
        "",
        "**📊 정산 내역**",
        f"판매금 (거래소 수수료 제외 후) : `{판매금:,}메소`",
    ]
    if 카르마가위 > 0:
        lines.append(f"카르마의 가위 : `-{카르마가위:,}메소`")
    lines.extend([
        "━━━━━━━━━━━━━━━━━━━",
        f"정산 금액 : `{after_karma:,}메소`",
        f"÷ {파티원수}명 → **1인당 분배금 (P) : `{P:,}메소`**",
    ])

    if n_receivers == 0:
        # 혼자 분배 — 택배 X
        lines.extend([
            "",
            "👤 **혼자 받음** — 택배 송금 불필요, 수수료 없음",
            "",
            "💰 **최종 수령액**",
            f"## `{distributor_amount:,}` 메소",
        ])
    else:
        # 역산 결과
        c_sign = "+" if C >= 0 else "−"
        c_abs = abs(C)
        lines.extend([
            "",
            "**🎯 송금 금액 역산**",
            f"P 구간 : `{bracket_label}` → r = `{r_pct:g}%`, C = `{c_sign}{c_abs:,}`",
            f"S = (P {c_sign} {c_abs:,}) ÷ (1 + {r_pct:g}%) → 정수 보정 → **`{S:,}메소`**",
            f"검증 : S + fee(S) = `{S:,}` + `{fee_per_send:,}` = `{S + fee_per_send:,}` = P ✅",
            "",
            f"**🚚 1건당 수수료 산출** (S = `{S:,}메소` 기준 · 누진)",
        ])
        if breakdown:
            for label, ba, rp, bf in breakdown:
                lines.append(f"• `{label}` : {ba:,} × {rp:g}% = `{bf:,}메소`")
        else:
            lines.append("• `10만 메소 미만` 구간 → 누진 수수료 0")
        lines.append(f"• `기본료` : `{PARCEL_BASE_FEE:,}메소`")
        lines.extend([
            "━━━━━━━━━━━━━━━━━━━",
            f"1건당 수수료 합계 : `{fee_per_send:,}메소`",
            "",
            "**📤 분배자 → 다른 파티원 (1건당)**",
            f"• 📝 택배 입력 금액 (S) : `{S:,}메소`  ← _이 값을 택배에 입력_",
            f"• 💸 분배자 추가 지불 수수료 : `{fee_per_send:,}메소`",
            f"• 💼 분배자 1건당 총 지출 : `{P:,}메소` _(= S + fee = P)_",
            f"• 🎁 받는 사람 수령액 : `{S:,}메소`",
            "",
            "**💰 1인당 최종 수령**",
            f"• 분배자 (`{distributor_name}`) : `{distributor_amount:,}메소` _(택배 X · 수수료 0)_",
            f"• 다른 파티원 ({n_receivers}명) : 각 `{receiver_amount:,}메소`",
            "",
            "**💸 분배자 부담 합계**",
            f"• 총 택배 수수료 : `{fee_per_send:,} × {n_receivers}회` = `-{total_fees:,}메소`",
            f"• 총 지출 : `{P:,} × {파티원수}` = `{total_distributor_spend:,}메소` _(정산 금액 전부 사용)_",
        ])

    if remainder:
        lines.append(f"\n_분배 시 나머지 {remainder:,}메소는 버림 처리되었어요._")

    # 분배 내역 (2명 이상)
    if 파티원수 >= 2:
        lines.append("")
        lines.append("**📦 분배 내역**")
        lines.append(f"• 분배자 (`{distributor_name}`) : `{distributor_amount:,}메소`")
        for i in range(2, 파티원수 + 1):
            lines.append(f"• 파티원 {i} : `{receiver_amount:,}메소`")

    embed = discord.Embed(
        title=f"🍁 [ {아이템명} ] 판매 수익금 분배",
        description="\n".join(lines),
        color=0xE74C3C,
    )
    embed.set_footer(
        text=(
            f"역산 방식 · 받는 사람 수령액 = S, 분배자 1건당 지출 = P "
            f"· 요청: {distributor_name}"
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
