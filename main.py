import discord
from discord.ext import commands
from openai import OpenAI
import requests
from urllib.parse import quote_plus  # URL 인코딩용
import os # NEXON_API_KEY를 환경 변수에서 가져올 때 사용 (주석 처리)
import random
import sqlite3
import re
from discord import app_commands
import asyncio

from flask import Flask
from threading import Thread

app = Flask('')

@app.route('/')
def home():
    return "봇이 잘 돌아가고 있어요!"

def run():
    app.run(host='0.0.0.0', port=8000)  # 8000 포트는 koyeb에서 연결한 포트여야 해

def keep_alive():
    t = Thread(target=run)
    t.start()

keep_alive()


TOKEN = os.getenv("TOKEN")
if not TOKEN:
    print("경고 : 봇 토큰을 설정해 주세요! TOKEN 환경 변수에 실제 봇 토큰을 입력해야 합니다.")

NEXON_API_KEY = os.getenv("NEXON_API_KEY")
if not NEXON_API_KEY:
    print("경고 : 봇 토큰을 설정해 주세요! 넥API 환경 변수에 실제 봇 토큰을 입력해야 합니다.")

ADMIN_USER_ID = os.getenv("ADMIN_USER_ID")
if not ADMIN_USER_ID:
    print("경고 : 봇 토큰을 설정해 주세요! AD유저ID 환경 변수에 실제 봇 토큰을 입력해야 합니다.")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    print("경고 : 봇 토큰을 설정해 주세요! openai 환경 변수에 실제 봇 토큰을 입력해야 합니다.")

DB_FILE_PATH = 'bot_data.db'

active_number_games = {}

async def on_submit(self, interaction: discord.Interaction):
    try:
        admin_user = await interaction.client.fetch_user(ADMIN_USER_ID)
        await admin_user.send( ... )  # DM 전송

        # 최초 응답: 메시지 전송
        await interaction.response.send_message(
            "문의가 정상 접수되었습니다!", ephemeral=True
        )
    except Exception as e:
        print(f"관리자 DM 전송 실패: {e}")
        # 에러 발생 시도 처리
        # 이미 응답했을 수 있으므로 followup 사용
        if interaction.response.is_done():
            await interaction.followup.send(
                "오류가 발생했습니다. 나중에 다시 시도해주세요.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "오류가 발생했습니다. 나중에 다시 시도해주세요.", ephemeral=True
            )


# --- SQLite DB 헬퍼 함수들 ---
def setup_database():
    conn = None
    print(f"[DB LOG] setup_database() 함수 시작. DB 파일: {DB_FILE_PATH}") # <<< 이 로그가 뜨나요?
    try:
        conn = sqlite3.connect(DB_FILE_PATH, check_same_thread=False)
        cursor = conn.cursor()
        print("[DB LOG] 연결 성공, 커서 생성.") # <<< 이 로그가 뜨나요?
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                points INTEGER DEFAULT 0
            )
        ''')
        conn.commit() # 변경사항 저장
        print("[DB LOG] 'users' 테이블 생성 (또는 이미 존재 확인) 및 커밋 완료.") # <<< 이 로그가 뜨나요?
        print(f"[DB LOG] 데이터베이스 '{DB_FILE_PATH}' 연결 및 'users' 테이블 준비 완료!")
    except sqlite3.Error as e:
        print(f"[DB LOG] 데이터베이스 오류 발생 (setup_database): {e}") # <<< 에러가 뜨나요?
    finally:
        if conn:
            conn.close() # 연결 종료
            print("[DB LOG] 데이터베이스 연결 종료.") # <<< 이 로그가 뜨나요?



def get_user_points(user_id: str) -> int:
    conn = None
    try:
        conn = sqlite3.connect(DB_FILE_PATH, check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('SELECT points FROM users WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        return result[0] if result else 0 # 사용자가 없으면 0점 반환
    except sqlite3.Error as e:
        print(f"[DB] 포인트 조회 중 데이터베이스 오류 발생: {e}")
        return 0
    finally:
        if conn:
            conn.close()

def update_user_points(user_id: str, amount: int):
    conn = None
    try:
        conn = sqlite3.connect(DB_FILE_PATH, check_same_thread=False)
        cursor = conn.cursor()
        # 사용자가 없으면 0점으로 추가 (UPSERT)
        cursor.execute('INSERT OR IGNORE INTO users (user_id, points) VALUES (?, ?)', (user_id, 0))
        # 포인트 업데이트
        cursor.execute('UPDATE users SET points = points + ? WHERE user_id = ?', (amount, user_id))
        conn.commit()
        print(f"[DB] 유저 {user_id}의 포인트가 {amount}만큼 업데이트되었습니다.")
    except sqlite3.Error as e:
        print(f"[DB] 포인트 업데이트 중 데이터베이스 오류 발생: {e}")
    finally:
        if conn:
            conn.close()

def set_user_points(user_id: str, new_points: int): # 관리자용이나 초기 설정용
    conn = None
    try:
        conn = sqlite3.connect(DB_FILE_PATH, check_same_thread=False)
        cursor = conn.cursor()
        # 사용자가 없으면 추가하고, 있으면 업데이트 (UPSERT)
        cursor.execute('INSERT OR REPLACE INTO users (user_id, points) VALUES (?, ?)', (user_id, new_points))
        conn.commit()
        print(f"[DB] 유저 {user_id}의 포인트가 {new_points}점으로 설정되었습니다.")
    except sqlite3.Error as e:
        print(f"[DB] 포인트 설정 중 데이터베이스 오류 발생: {e}")
    finally:
        if conn:
            conn.close()


# 봇의 접두어 설정
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents)

TEST_GUILD_ID = 1417736200701349970

client = OpenAI(api_key=OPENAI_API_KEY)

# --- 모달 (Modal) 정의: /민준 명령어를 위한 질문 창 ---
class MinjunPromptModal(discord.ui.Modal, title="민준이에게 질문하기"):
    # 사용자에게 질문을 입력받을 텍스트 입력 필드
    user_prompt_input = discord.ui.TextInput(
        label="궁금한 것을 입력해주세요!",
        style=discord.TextStyle.paragraph, # 여러 줄 입력 가능하게 설정
        placeholder="그 무엇이든 물어보세요... 이상한 것만 아니면 될 것 같아요.",
        required=True, # 필수 입력 필드
        max_length=1000, # 최대 1000자까지 입력 가능
    )

    async def on_submit(self, interaction: discord.Interaction):
        # 사용자가 모달 창에 입력한 내용을 가져옴
        prompt = self.user_prompt_input.value

        # 답변이 올 때까지 '생각 중...' 메시지를 먼저 보냄 (사라지는 메시지)
        await interaction.response.send_message(f"**{interaction.user.display_name}**님의 질문: `{prompt}`\n\n민준이가 열심히 생각 중이에요...", ephemeral=True)

        try:
            # OpenAI API 호출
            response = client.chat.completions.create(
                model="gpt-4o-mini",  # 또는 "gpt-3.5-turbo"
                messages=[
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=500, # 답변의 최대 길이를 늘려줌
                temperature=0.7
            )

            # 응답 내용 추출
            answer = response.choices[0].message.content.strip()

            # 디스코드 메시지는 2000자 제한이 있으니 잘라서 전송
            # interaction.followup.send를 사용하여 최초 응답 이후 메시지 전송
            if len(answer) > 2000:
                # 첫 2000자는 기존 메시지를 편집해서 보냄
                await interaction.edit_original_response(content=f"**{interaction.user.display_name}**님의 질문: `{prompt}`\n\n**민준이의 답변:**\n{answer[0:2000]}")
                for i in range(2000, len(answer), 2000):
                    await interaction.followup.send(answer[i:i+2000], ephemeral=True) # 나머지는 새로운 메시지로 보냄
            else:
                await interaction.edit_original_response(content=f"**{interaction.user.display_name}**님의 질문: `{prompt}`\n\n**민준이의 답변:**\n{answer}")

        except Exception as e:
            await interaction.followup.send(f"앗, 에러가 발생했습니다..: {e}", ephemeral=True)


# --- 슬래시 커맨드 정의: /민준 ---
@bot.tree.command(name="민준", description="민준이에게 질문하고 답변을 받아볼래요?")
async def 민준_슬래시(interaction: discord.Interaction):
    # /민준 명령어를 사용하면 위에 정의한 모달(MinjunPromptModal)을 보여줌
    await interaction.response.send_modal(MinjunPromptModal())

@bot.event
async def on_ready():
    print(f'{bot.user} 디스코드 접속.')
    print("DEBUG: on_ready 이벤트 시작.") # 추가
    try:
        print("DEBUG: bot.tree.sync() 호출 전.") # 추가
        synced = await bot.tree.sync()
        print("DEBUG: bot.tree.sync() 호출 후.") # 추가
        print(f"{len(synced)}개의 슬래시 커맨드가 동기화되었습니다.")
    except Exception as e:
        print(f"DEBUG: 슬래시 커맨드 동기화 중 오류 발생: {e}") # 메시지 수정
    print("DEBUG: on_ready 이벤트 종료.") # 추가

##개발자문의 관련 코드


# --- 문의 내용을 입력받을 모달(Modal) 클래스 정의 ---
class InquiryModal(discord.ui.Modal, title='개발자에게 문의 작성'):
    # 문의 내용을 입력받을 텍스트 입력창
    inquiry_text_input = discord.ui.TextInput(
        label='자세한 문의 내용을 작성해주세요.',
        style=discord.TextStyle.paragraph, # 여러 줄 입력 가능
        max_length=1000, # 최대 1000자
        required=True, # 필수로 입력해야 함
        placeholder='문의할 내용을 여기에 입력해주세요.'
    )

    # 모달 제출(Submit) 버튼을 눌렀을 때 실행될 비동기 함수
    async def on_submit(self, interaction: discord.Interaction):
        user = interaction.user # 문의를 보낸 사용자 정보
        inquiry_content = self.inquiry_text_input.value # 입력받은 문의 내용

        # !!! 파일 최상단에 정의된 ADMIN_USER_ID 변수를 사용합니다 !!!
        global ADMIN_USER_ID # ADMIN_USER_ID가 전역 변수로 선언되어 있다고 가정

        try:
            # 관리자 유저 객체를 가져옴
            admin_user = await interaction.client.fetch_user(ADMIN_USER_ID)

            # 관리자에게 보낼 DM 메시지 내용
            dm_message = (
                f"📬 새로운 개발자 문의가 접수되었습니다!\n"
                f"--------------------------------------------------\n"
                f"**문의자**: {user.name}#{user.discriminator} (ID: `{user.id}`)\n" # 사용자 이름과 ID를 함께 보냄
                f"**문의 내용**:\n>>> {inquiry_content}\n"
                f"--------------------------------------------------"
            )

            # 관리자에게 DM 전송
            await admin_user.send(dm_message)

            # 사용자에게 문의가 성공적으로 접수되었음을 알림 (사용자에게만 보이는 메시지)
            await interaction.response.send_message(
                '💌 문의가 성공적으로 접수되었습니다. 개발자가 확인 후 빠른 시일 내에 답변드릴게요!', 
                ephemeral=True # 이 메시지는 명령어를 사용한 사람에게만 보여요.
            )
        except Exception as e:
            print(f"[ERROR] 관리자 DM 전송 실패 또는 다른 오류 발생: {e}")
            await interaction.response.send_message(
                f'⚠️ 문의 전송 중 오류가 발생했습니다. 나중에 다시 시도해주세요. (오류: {e})',
                ephemeral=True
            )


# --- 슬래시 명령어 정의 ---

# `/개발자문의` 명령어 (길드 지정 없음 = 글로벌 명령어)
@bot.tree.command(name='개발자문의', description='개발자에게 문의 내용을 보냅니다.') # <-- guild= 부분이 없어졌어
async def developer_inquiry_command(interaction: discord.Interaction):
    # 이 명령어를 입력하면 위에서 정의한 InquiryModal이 사용자에게 팝업으로 나타납니다.
    modal = InquiryModal()
    await interaction.response.send_modal(modal)



## 대화청소 관련 코드

@bot.tree.command(name="대화청소", description="본인과 봇 사이의 특정 답장 대화를 삭제합니다.")
async def clear_conversation(interaction: discord.Interaction):
    # 봇이 처리 중임을 알리고, 나중에 메시지를 보낸 사람에게만 보이도록 ephemeral=True 설정
    await interaction.response.defer(ephemeral=True)

    channel = interaction.channel # 명령어가 사용된 채널
    user_to_clean = interaction.user # 명령어를 사용한 유저 (너)
    bot_user = interaction.client.user # 봇 자신

    message_ids_to_delete = set() # 삭제할 메시지 ID들을 담을 집합 (중복 방지)

    # 최근 200개의 메시지 이력을 확인 (필요에 따라 limit 값을 조절할 수 있어)
    async for msg in channel.history(limit=200):
        # 1. 메시지 작성자가 봇인 경우
        if msg.author == bot_user:
            # 봇 메시지가 '답장' 형태인지 확인 (msg.reference.resolved가 원본 메시지를 가리킴)
            if msg.reference:
                referenced_message = msg.reference.resolved

                # 답장된 원본 메시지가 유효하고 (삭제되지 않았고), 그 작성자가 user_to_clean이라면
                if isinstance(referenced_message, discord.Message) and referenced_message.author == user_to_clean:
                    message_ids_to_delete.add(msg.id) # 봇의 답장 메시지 ID 추가
                    message_ids_to_delete.add(referenced_message.id) # 유저의 원본 메시지 ID 추가

            # (선택적) 봇이 보낸 일반적인 명령 응답 메시지(interaction.followup.send 등)도 삭제하고 싶다면
            # 여기서는 user_to_clean의 직접적인 메시지 답장이 아니므로 위 조건에 해당되지 않아.
            # 하지만 봇의 "/개발자문의" 응답처럼 특정 커맨드에 대한 봇의 직접적인 첫 응답도 삭제하고 싶다면,
            # 메시지 내용이나 봇이 이전에 전송했던 메시지 ID를 추적하는 더 복잡한 로직이 필요해.
            # 지금은 "봇의 답장 및 그 원본 메시지"라는 요청에 최대한 집중할게.

        # 2. 명령어를 사용한 유저 (너)가 보낸 '/대화청소' 명령어 메시지 삭제
        # 참고: 슬래시 명령어 입력 자체는 Discord의 메시지 이력에 남는 일반 메시지가 아니라서,
        # '채팅창에 입력한 /대화청소' 그 자체는 이 방법으로 삭제하기 어려워.
        # 여기서는 혹시 몰라 일반 메시지로 '/'로 시작하는 내용을 입력하는 경우를 위해 넣어둘게.
        elif msg.author == user_to_clean and msg.content.startswith('/대화청소'):
            message_ids_to_delete.add(msg.id)

    # 이제, 실제로 삭제할 메시지 ID들이 모인 set을 가지고 메시지를 삭제
    deleted_count = 0
    if message_ids_to_delete:
        # discord.Message 객체 리스트로 변환 (purge 함수는 Message 객체 리스트도 받음)
        # 하지만 이미 ID로만 모았으니, ID를 하나씩 넘겨주는 대신 delete_messages를 쓰는게 효율적

        # NOTE: channel.purge()는 check 함수를 메시지별로 호출하면서 유효성 검사를 하지만,
        #       우리는 이미 위에 msg.id를 다 모았으므로, 사실상 이 메시지들을 일괄 삭제하는 것이 더 효율적이야.
        #       channel.delete_messages()를 사용하는 게 더 직관적일 수 있어.
        #       하지만 purge가 안전성 검사 (예: pinned messages)를 좀 더 잘 하므로, purge를 활용해볼게.
        #       (check 함수를 간단하게 만들어 활용하는 식으로)

        # check 함수는 purge가 순회하는 메시지 객체의 ID가 우리가 모은 ID 중 하나인지 확인
        def final_purge_check(message):
            return message.id in message_ids_to_delete

        deleted_messages = await channel.purge(limit=200, check=final_purge_check)
        deleted_count = len(deleted_messages)

    # 사용자에게 결과 피드백
    await interaction.followup.send(
        f"{user_to_clean.mention}님과 봇 사이에서 주고받은 {deleted_count}개의 관련 메시지를 삭제했어요.",
        ephemeral=True
    )

## 미니게임 관련 코드

# --- 미니게임 로직 함수: 로또 뽑기 ---
async def start_lotto_game(interaction: discord.Interaction):
    # 1부터 45까지 숫자 중에서 6개를 중복 없이 뽑기
    lotto_numbers = random.sample(range(1, 46), 6)
    lotto_numbers.sort() # 보기 좋게 오름차순 정렬

    lotto_str = " ".join([f"**{num:02d}**" for num in lotto_numbers]) # 숫자 앞에 0을 붙여 두 자리로, 볼드 처리

    embed = discord.Embed(
        title="✨ 행운의 로또 번호 ✨",
        description=f"{interaction.user.mention}님을 위한 이번 주 로또 번호는...?\n\n"
                    f"### {lotto_str}\n\n"
                    f"입니다! 대박 기운 받으세요! 💰",
        color=discord.Color.red()
    )
    embed.set_footer(text="혹시.. 당첨인가요? 🌙") #
    await interaction.followup.send(embed=embed)

# --- 룰렛 게임 (DB 연동) ---
async def start_roulette_game(interaction: discord.Interaction):
    user_id_str = str(interaction.user.id) # DB에 user_id를 문자열로 저장
    choices = [
        {"name": "+100 포인트 획득! (100점)", "amount": 100, "emoji": "🎉"},
        {"name": "아쉽지만 다음 기회에... (0점)", "amount": 0, "emoji": "😅"},
        {"name": "+50 포인트 획득! (50점)", "amount": 50, "emoji": "💰"},
        {"name": "꽝! -20 포인트... (-20점)", "amount": -20, "emoji": "💀"}
    ]

    selected_choice = random.choice(choices)

    current_points = get_user_points(user_id_str) # DB에서 현재 포인트 조회
    update_user_points(user_id_str, selected_choice["amount"]) # DB 포인트 업데이트
    new_points = get_user_points(user_id_str) # 업데이트 후 포인트 다시 조회

    embed = discord.Embed(
        title=f"{interaction.user.display_name}님의 룰렛 결과!",
        description=f"{selected_choice['emoji']} {selected_choice['name']}\n\n"
                    f"현재 포인트: **{current_points}점** ➡️ **{new_points}점**",
        color=discord.Color.gold()
    )
    await interaction.followup.send(embed=embed)

# --- 숫자 맞히기 게임 ---
async def start_number_guessing_game(interaction: discord.Interaction):
    # 게임 상태 확인
    if interaction.channel_id in active_number_games:
        await interaction.followup.send(
            "이 채널에서는 이미 숫자 맞히기 게임이 진행 중이에요! 게임이 끝날 때까지 기다려 주세요."
        )
        return

    min_num = 1
    max_num = 100
    secret_number = random.randint(min_num, max_num)
    attempts = 0 # 시도 횟수

    # 게임 상태 저장
    active_number_games[interaction.channel_id] = {
        "secret_number": secret_number,
        "attempts": attempts,
        "player_id": interaction.user.id,
        "min_range": min_num,
        "max_range": max_num
    }

    embed = discord.Embed(
        title="🔢 숫자 맞히기 게임 시작!",
        description=f"{interaction.user.mention}님, 제가 {min_num}부터 {max_num}까지의 숫자 중 하나를 생각했어요.\n"
                    "채팅창에 숫자를 입력해서 맞춰보세요! (예: `50`)",
        color=discord.Color.blurple()
    )
    await interaction.followup.send(embed=embed)

# --- 미니게임 선택 뷰 (버튼 클릭 처리를 담당) ---
class MiniGameSelectView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180) # 3분 동안 상호작용 없으면 버튼 비활성화

    @discord.ui.button(label="로또 뽑기", style=discord.ButtonStyle.success, custom_id="minigame_lotto")
    async def lotto_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="숫자를 뽑는 중...", view=None)
        await start_lotto_game(interaction)

    @discord.ui.button(label="룰렛", style=discord.ButtonStyle.danger, custom_id="minigame_roulette")
    async def roulette_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="🎰 룰렛 게임을 시작합니다!", view=None)
        await start_roulette_game(interaction)

    @discord.ui.button(label="숫자 맞히기", style=discord.ButtonStyle.blurple, custom_id="minigame_number_guess")
    async def number_guess_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="숫자 맞히기 게임을 준비합니다!", view=None)
        await start_number_guessing_game(interaction)

    @discord.ui.button(label="끝말잇기", style=discord.ButtonStyle.primary, custom_id="minigame_wordchain", disabled=True)
    async def wordchain_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("💬 끝말잇기 게임은 아직 준비 중입니다! 기대해주세요!", ephemeral=True)

    @discord.ui.button(label="초성 퀴즈", style=discord.ButtonStyle.secondary, custom_id="minigame_quiz", disabled=True)
    async def quiz_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("❓ 초성 퀴즈 게임은 아직 준비 중입니다! 기대해주세요!", ephemeral=True)

    @discord.ui.button(label="스무고개", style=discord.ButtonStyle.secondary, custom_id="minigame_20questions", disabled=True)
    async def twenty_questions_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("🤔 스무고개 게임은 아직 준비 중입니다! 기대해주세요!", ephemeral=True)

    @discord.ui.button(label="행맨", style=discord.ButtonStyle.secondary, custom_id="minigame_hangman", disabled=True)
    async def hangman_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("📝 행맨 게임은 아직 준비 중입니다! 기대해주세요!", ephemeral=True)

    @discord.ui.button(label="찬반 토론", style=discord.ButtonStyle.secondary, custom_id="minigame_debate", disabled=True)
    async def debate_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("📢 찬반 토론 게임은 아직 준비 중입니다! 기대해주세요!", ephemeral=True)

    @discord.ui.button(label="랜덤 미션", style=discord.ButtonStyle.secondary, custom_id="minigame_mission", disabled=True)
    async def mission_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("🎁 랜덤 미션 게임은 아직 준비 중입니다! 기대해주세요!", ephemeral=True)

    @discord.ui.button(label="나의 TMI", style=discord.ButtonStyle.secondary, custom_id="minigame_tmi", disabled=True)
    async def tmi_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("🎤 나의 TMI 게임은 아직 준비 중입니다! 기대해주세요!", ephemeral=True)

# --- 봇 이벤트 핸들러 (메시지 처리 등) ---
@bot.event
async def on_message(message: discord.Message):
    # 봇 자신이 보낸 메시지는 무시
    if message.author.bot:
        return

    # 숫자 맞히기 게임이 이 채널에서 진행 중인지 확인
    if message.channel.id in active_number_games:
        game_state = active_number_games[message.channel.id]

        # 게임을 시작한 사람만 숫자를 맞힐 수 있게 하려면:
        if message.author.id != game_state["player_id"]:
            # await message.reply("🤫 이 게임은 당신이 시작한 게임이 아닙니다!") # 너무 시끄러울 수 있으니 주석처리
            pass
        else:
            try:
                guess = int(message.content)
                game_state["attempts"] += 1

                if guess == game_state["secret_number"]:
                    current_points = get_user_points(str(message.author.id))
                    point_reward = 10 # 숫자 맞히기 성공 보상
                    update_user_points(str(message.author.id), point_reward)
                    new_points = get_user_points(str(message.author.id))

                    embed = discord.Embed(
                        title="🎉 정답!",
                        description=f"{message.author.mention}님, **{guess}**가 정답이에요!\n"
                                    f"{game_state['attempts']}번 만에 맞히셨네요!\n"
                                    f"{point_reward} 포인트를 획득하여 현재 **{new_points}점**!",
                        color=discord.Color.green()
                    )
                    await message.reply(embed=embed)
                    del active_number_games[message.channel.id] # 게임 종료
                elif guess < game_state["secret_number"]:
                    await message.reply(f"⬆️ **{guess}**보다 높아요! ({game_state['attempts']}번째 시도)")
                else:
                    await message.reply(f"⬇️ **{guess}**보다 낮아요! ({game_state['attempts']}번째 시도)")

            except ValueError:
                # 숫자가 아닌 다른 메시지를 입력했을 때 무시 (혹은 경고)
                # await message.reply("숫자를 입력해주세요!") # 역시 너무 시끄러울 수 있음
                pass

    await bot.process_commands(message) # 다른 일반 명령어 처리를 위해 반드시 필요


# --- 슬래시 명령어 (minigame) ---
@bot.tree.command(name="미니게임", description="신나는 미니게임을 선택하여 즐겨보세요!")
async def minigame_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🎉 신나는 미니게임 목록 🎉",
        description="원하는 게임을 아래 버튼을 눌러 선택해주세요!\n"
                    "**룰렛**과 **숫자 맞히기**로 포인트를 얻어보세요!",
        color=discord.Color.blue()
    )
    embed.add_field(name="🍀 로또 뽑기", value="1부터 45까지! 당신의 행운의 로또 번호 6개를 뽑아드립니다!", inline=False)
    embed.add_field(name="🎰 룰렛", value="행운의 룰렛을 돌려 포인트를 얻거나 잃을 수 있습니다!", inline=False)
    embed.add_field(name="🔢 숫자 맞히기", value="제가 생각한 숫자를 가장 빠르게 맞춰보세요!", inline=False)
    embed.add_field(name="-- 이 외 게임들 (준비 중) --", value="끝말잇기, 초성 퀴즈, 스무고개, 행맨, 찬반 토론, 랜덤 미션, 나의 TMI 등", inline=False)

    embed.set_footer(text="버튼을 눌러 게임을 시작하세요!")

    # ephemeral=True 로 설정하면 명령어를 사용한 사람에게만 보임
    await interaction.response.send_message(embed=embed, view=MiniGameSelectView(), ephemeral=True)

def update_user_points(user_id: str, amount: int):
    print(f"포인트 업데이트 시도: user_id={user_id}, amount={amount}")
    conn = None
    try:
        conn = sqlite3.connect(DB_FILE_PATH, check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('INSERT OR IGNORE INTO users (user_id, points) VALUES (?, ?)', (user_id, 0))
        cursor.execute('UPDATE users SET points = points + ? WHERE user_id = ?', (amount, user_id))
        conn.commit()
        print(f"포인트 업데이트 완료: user_id={user_id}, amount={amount}")
    except sqlite3.Error as e:
        print(f"DB 오류: {e}")
    finally:
        if conn:
            conn.close()

def setup_database():
    conn = None
    try:
        conn = sqlite3.connect(DB_FILE_PATH, check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                points INTEGER DEFAULT 0
            )
        ''')
        conn.commit()
    except sqlite3.Error as e:
        print(f"데이터베이스 오류: {e}")
    finally:
        if conn:
            conn.close()







## 이 이후는 슈퍼바이브 전적 관련 코드

SUPERVIBE_API_BASE_URL = "https://open.api.nexon.com"

headers = {
    "x-nxopen-api-key": NEXON_API_KEY,  # 넥슨 API 키
    "Accept": "application/json"
}


@bot.tree.command(name="슈퍼바이브프로필", description="닉네임#태그로 레벨과 랭크 정보를 알려줍니다.")
@discord.app_commands.describe(nickname="플레이어 닉네임과 태그 (예: 태양신님재가그걔에요#DEAR)")
async def supervibe_profile(interaction: discord.Interaction, nickname: str):
    await interaction.response.send_message(f"`{nickname}` 님 프로필을 조회합니다...", ephemeral=True)

    # 1. ouid 조회용 유저 정보 API 호출
    user_id_url = f"{SUPERVIBE_API_BASE_URL}/supervive/v1/id"
    params_id = {"user_name": nickname} # 닉네임과 태그 포함 전체

    try:
        res_id = requests.get(user_id_url, headers=headers, params=params_id)
        res_id.raise_for_status()
        id_data = res_id.json()

        ouid = id_data.get("ouid")
        if not ouid:
            data_field = id_data.get("data")
            if isinstance(data_field, dict):
                ouid = data_field.get("ouid") or data_field.get("id")
            elif isinstance(data_field, list) and data_field:
                ouid = data_field[0].get("ouid") or data_field[0].get("id")

        if not ouid:
            await interaction.edit_original_response(content=f"플레이어 `{nickname}` 님의 고유 ID(ouid)를 찾을 수 없습니다. 닉네임을 다시 확인해 주세요.")
            return

        # 2. ouid를 바탕으로 프로필 정보 조회
        profile_url = f"{SUPERVIBE_API_BASE_URL}/supervive/v1/user-profile"
        params_profile = {"ouid": ouid}

        res_profile = requests.get(profile_url, headers=headers, params=params_profile)
        res_profile.raise_for_status()
        profile_data = res_profile.json()

        display_name = profile_data.get("display_name", "정보 없음")
        tag = profile_data.get("tag", "")
        account_level = profile_data.get("account_level", "정보 없음")

        ranks_info = profile_data.get("rank", [])

        # 랭크 등급 한글명 매핑
        rank_name_map = {
            "IRON": "아이언",
            "BRONZE": "브론즈",
            "SILVER": "실버",
            "GOLD": "골드",
            "PLATINUM": "플래티넘",
            "DIAMOND": "다이아몬드",
            "MASTER": "마스터",
            "GRANDMASTER": "그랜드마스터",
            "LEGEND": "레전드" # 레전드 랭크도 추가
        }

        # 랭크 정보가 여러 개일 수 있으니, 대표 랭크(예: DEFAULT 타입)를 찾아 처리
        selected_rank = None
        for rank_entry in ranks_info:
            if rank_entry.get("rank_type") == "DEFAULT": # 보통 'DEFAULT' 타입이 주요 랭크
                selected_rank = rank_entry
                break

        # DEFAULT 타입이 없으면 첫 번째 랭크라도 사용
        if not selected_rank and ranks_info:
            selected_rank = ranks_info[0]

        rank_str = "랭크 정보 없음" # 기본값

        if selected_rank:
            import re
            rank_grade_raw = selected_rank.get("rank_grade", "정보 없음") # 예: Master3
            rating = selected_rank.get("rating", "정보 없음") # 예: 144

            rank_display_name = rank_grade_raw # 일단 원본 텍스트로 초기화

            # 등급에서 영어 부분과 숫자 부분 분리 (예: "Master3" -> "Master", "3")
            match = re.match(r"([A-Za-z]+)(\d*)", rank_grade_raw)
            if match:
                eng_rank_name, rank_level = match.groups()
                # 영어 등급명을 한글로 변환
                kor_rank_name = rank_name_map.get(eng_rank_name.upper(), eng_rank_name)
                # 한글 등급명에 숫자 단계를 붙여서 최종 랭크명 생성
                rank_display_name = f"{kor_rank_name}{rank_level}"

            # 최종 랭크 문자열 (예: "마스터3 (144점)" 또는 "레전드 4004점")
            if rating != "정보 없음":
                rank_str = f"{rank_display_name} ({rating}점)"
            else:
                rank_str = rank_display_name
        else:
            rank_str = "랭크 정보 없음"

        embed = discord.Embed(title=f"{display_name}#{tag} 님의 슈퍼바이브 프로필", color=0x00ff00)
        embed.add_field(name="레벨", value=account_level, inline=False)
        embed.add_field(name="랭크", value=rank_str, inline=False) # 여기에 최종 rank_str 사용
        embed.set_footer(text="데이터 제공: 넥슨 Open API")

        await interaction.edit_original_response(content=None, embed=embed)

    except requests.exceptions.HTTPError as http_err:
        err_msg = http_err.response.text if http_err.response else str(http_err)
        await interaction.edit_original_response(content=f"해당 유저를 찾을 수 없습니다.")
    except Exception as ex:
        await interaction.edit_original_response(content=f"알 수 없는 오류가 발생했습니다: {str(ex)}")


        # 3. 결과를 디스코드 임베드에 예쁘게 출력
        embed = discord.Embed(title=f"{display_name}#{tag} 님의 슈퍼바이브 프로필", color=0x00ff00)
        embed.add_field(name="레벨", value=account_level, inline=False)
        embed.add_field(name="랭크", value=rank_str, inline=False)
        embed.set_footer(text="데이터 제공: 넥슨 Open API")

        await interaction.edit_original_response(content=None, embed=embed)

    except requests.exceptions.HTTPError as http_err:
        err_msg = http_err.response.text if http_err.response else str(http_err)
        await interaction.edit_original_response(content=f"해당 유저를 찾을 수 없습니다.")
    except Exception as ex:
        await interaction.edit_original_response(content=f"알 수 없는 오류가 발생했습니다: {str(ex)}")

## 이 이후는 슈퍼바이브 헌터 관련 코드

hunter_data = [
    {"name": "슈라이크", "image_url": "https://open.api.nexon.com/static/supervive/img/8e296c912fc477093a73c14dacbba038"},
    {"name": "고스트", "image_url": "https://open.api.nexon.com/static/supervive/img/0ac36510d9b17b8222acf022167fe2a6"},
    {"name": "머큐리", "image_url": "https://open.api.nexon.com/static/supervive/img/8e296c912fc477093a73c14dacbba038"},
    {"name": "미쓰", "image_url": "https://open.api.nexon.com/static/supervive/img/0ac36510d9b17b8222acf022167fe2a6"},
    {"name": "보이드", "image_url": "https://open.api.nexon.com/static/supervive/img/8e296c912fc477093a73c14dacbba038"},
    {"name": "브랄", "image_url": "https://open.api.nexon.com/static/supervive/img/0ac36510d9b17b8222acf022167fe2a6"},
    {"name": "비보", "image_url": "https://cdn.discordapp.com/attachments/1417736200701349972/1422167362731380898/beebo_dash.png?ex=68dbb011&is=68da5e91&hm=98ab8d10852276e2e8aa92d2f6073b283d496b09912682d6811f77a99c2a575d&"},
    {"name": "비숍", "image_url": "https://open.api.nexon.com/static/supervive/img/0ac36510d9b17b8222acf022167fe2a6"},
    {"name": "사로스", "image_url": "https://open.api.nexon.com/static/supervive/img/8e296c912fc477093a73c14dacbba038"},
    {"name": "셀레스트", "image_url": "https://open.api.nexon.com/static/supervive/img/0ac36510d9b17b8222acf022167fe2a6"},
    {"name": "쉬브", "image_url": "https://open.api.nexon.com/static/supervive/img/8e296c912fc477093a73c14dacbba038"},
    {"name": "엘루나", "image_url": "https://open.api.nexon.com/static/supervive/img/0ac36510d9b17b8222acf022167fe2a6"},
    {"name": "오공", "image_url": "https://open.api.nexon.com/static/supervive/img/8e296c912fc477093a73c14dacbba038"},
    {"name": "오쓰", "image_url": "https://open.api.nexon.com/static/supervive/img/0ac36510d9b17b8222acf022167fe2a6"},
    {"name": "이바", "image_url": "https://open.api.nexon.com/static/supervive/img/8e296c912fc477093a73c14dacbba038"},
    {"name": "제프", "image_url": "https://open.api.nexon.com/static/supervive/img/0ac36510d9b17b8222acf022167fe2a6"},
    {"name": "쥴", "image_url": "https://open.api.nexon.com/static/supervive/img/8e296c912fc477093a73c14dacbba038"},
    {"name": "진", "image_url": "https://open.api.nexon.com/static/supervive/img/0ac36510d9b17b8222acf022167fe2a6"},
    {"name": "칼바인", "image_url": "https://open.api.nexon.com/static/supervive/img/8e296c912fc477093a73c14dacbba038"},
    {"name": "크리스타", "image_url": "https://open.api.nexon.com/static/supervive/img/0ac36510d9b17b8222acf022167fe2a6"},
    {"name": "킹핀", "image_url": "https://open.api.nexon.com/static/supervive/img/8e296c912fc477093a73c14dacbba038"},
    {"name": "테트라", "image_url": "https://open.api.nexon.com/static/supervive/img/0ac36510d9b17b8222acf022167fe2a6"},
    {"name": "허드슨", "image_url": "https://open.api.nexon.com/static/supervive/img/8e296c912fc477093a73c14dacbba038"},
    {"name": "펠릭스", "image_url": "https://open.api.nexon.com/static/supervive/img/0ac36510d9b17b8222acf022167fe2a6"},

    # ... 실제 데이터는 더 많음 ...
    # 다 채워야지 인마.......
]

class HunterPageView(discord.ui.View):
    def __init__(self, hunters, page=0, per_page=25):
        super().__init__(timeout=180)
        self.hunters = hunters
        self.page = page
        self.per_page = per_page
        self.max_page = (len(hunters) - 1) // per_page
        self.update_items()

    def update_items(self):
        self.clear_items()

        # 이전 버튼
        if self.page > 0:
            self.add_item(self.PreviousButton())
        # 다음 버튼
        if self.page < self.max_page:
            self.add_item(self.NextButton())
        # 헌터 선택 드롭다운
        start = self.page * self.per_page
        end = start + self.per_page
        page_hunters = self.hunters[start:end]

        options = [
            discord.SelectOption(label=h["name"], description=h["name"], value=str(i))
            for i, h in enumerate(page_hunters)
        ]
        self.add_item(HunterSelect(options, page_hunters))

    async def update_embed(self, interaction):
        start = self.page * self.per_page
        end = start + self.per_page
        page_hunters = self.hunters[start:end]
        desc = "\n".join(f"- {h['name']}" for h in page_hunters)
        embed = discord.Embed(title=f"슈퍼바이브의 헌터 목록 ({self.page + 1}/{self.max_page + 1})",
                              description=desc,
                              color=discord.Color.blue())
        embed.set_footer(text="아래에서 헌터를 선택하면 정보를 출력해드려요.")
        await interaction.response.edit_message(embed=embed, view=self)

    class PreviousButton(discord.ui.Button):
        def __init__(self):
            super().__init__(label="◀ 이전", style=discord.ButtonStyle.primary)

        async def callback(self, interaction):
            view: HunterPageView = self.view
            view.page -= 1
            view.update_items()
            await view.update_embed(interaction)

    class NextButton(discord.ui.Button):
        def __init__(self):
            super().__init__(label="다음 ▶", style=discord.ButtonStyle.primary)

        async def callback(self, interaction):
            view: HunterPageView = self.view
            view.page += 1
            view.update_items()
            await view.update_embed(interaction)

class HunterSelect(discord.ui.Select):
    def __init__(self, options, hunters_in_page):
        super().__init__(placeholder="정보를 보고 싶은 헌터를 선택하세요.", options=options, min_values=1, max_values=1)
        self.hunters_in_page = hunters_in_page

    async def callback(self, interaction):
        selected_idx = int(self.values[0])
        hunter = self.hunters_in_page[selected_idx]
        embed = discord.Embed(title=hunter["name"], color=discord.Color.green())
        embed.set_image(url=hunter["image_url"])
        await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="슈퍼바이브헌터목록", description="준비된 헌터 목록을 페이지별로 보여드립니다.")
async def hunter_list(interaction: discord.Interaction):
    if not hunter_data:
        await interaction.response.send_message("헌터 데이터가 없어요..", ephemeral=True)
        return

    view = HunterPageView(hunter_data)
    start = 0
    end = view.per_page
    desc = "\n".join(f"- {h['name']}" for h in hunter_data[start:end])
    embed = discord.Embed(title=f"헌터 목록 (1/{view.max_page + 1})", description=desc, color=discord.Color.blue())
    embed.set_footer(text="아래에서 헌터를 선택해 정보를 확인하세요!")

    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

##

keep_alive()

# --- 봇 실행 ---
if __name__ == '__main__':
    # 봇 토큰이 올바른지 확인
    if TOKEN == "TOKEN":
        print("🚨 경고: 봇 토큰을 설정해주세요! TOKEN 변수에 실제 봇 토큰을 입력해야 합니다.")
    else:
        # DB 테이블 셋업은 봇 실행 전에!
        setup_database()
        bot.run(TOKEN) # 봇 실행