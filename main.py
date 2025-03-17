import discord
from discord.ext import commands, voice_recv
from dotenv import load_dotenv
import os

load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")

intents = discord.Intents.default()
intents.message_content = True

discord.opus._load_default()

# 유저별 음성 데이터를 저장할 딕셔너리 (user_id: [음성 청크, ...])
user_voice_data = {}


class MyBot(commands.Bot):
    async def setup_hook(self):
        await self.add_cog(Testing(self))

    async def on_ready(self):
        print("Logged in as {0.id}/{0}".format(self.user))
        print("------")


class Testing(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def join(self, ctx):
        """
        음성 채널에 연결하여 들어오는 음성 데이터를 유저별로 저장합니다.
        """

        def callback(user, data: voice_recv.VoiceData):
            print(f"Got packet from {user}")
            # voice_recv.VoiceData 객체의 data 필드에 음성 바이트 데이터가 있다고 가정
            audio_bytes = data.pcm

            # 해당 유저의 데이터가 없으면 리스트를 초기화
            if user.id not in user_voice_data:
                user_voice_data[user.id] = []

            # 음성 청크를 저장
            user_voice_data[user.id].append(audio_bytes)

        # 음성 채널에 접속한 경우에만 실행
        if ctx.author.voice and ctx.author.voice.channel:
            vc = await ctx.author.voice.channel.connect(cls=voice_recv.VoiceRecvClient)
            vc.listen(voice_recv.BasicSink(callback))
            await ctx.send("음성 데이터를 수신하기 시작합니다.")
        else:
            await ctx.send("먼저 음성 채널에 들어가주세요!")

    @commands.command()
    async def play(self, ctx):
        """
        저장된 음성 데이터를 불러와서 임시 파일에 저장 후, 음성 채널에서 재생합니다.
        """
        # 명령어를 실행한 유저의 저장된 데이터가 있는지 확인
        if ctx.author.id not in user_voice_data or not user_voice_data[ctx.author.id]:
            await ctx.send("저장된 음성 데이터가 없습니다.")
            return

        # 모든 청크를 하나의 바이트열로 결합
        combined_audio = b"".join(user_voice_data[ctx.author.id])
        temp_filename = f"{ctx.author.id}_voice.raw"

        # 결합한 음성 데이터를 임시 파일에 저장
        with open(temp_filename, "wb") as f:
            f.write(combined_audio)

        await ctx.send("저장된 음성 데이터를 사용합니다.")

        # 이미 음성 채널에 연결되어 있으면 해당 연결을 재사용
        if ctx.voice_client is None:
            if ctx.author.voice and ctx.author.voice.channel:
                vc = await ctx.author.voice.channel.connect()
            else:
                await ctx.send("음성 채널에 접속해주세요!")
                return
        else:
            vc = ctx.voice_client

        # 입력 파일이 raw PCM 데이터임을 FFmpeg에 알려주기 위해 before_options 사용
        source = discord.FFmpegPCMAudio(
            temp_filename, before_options="-f s16le -ar 48000 -ac 2"
        )
        vc.play(source)

    @commands.command()
    async def stop(self, ctx):
        if ctx.voice_client:
            await ctx.voice_client.disconnect()
        else:
            await ctx.send("봇이 음성 채널에 없습니다.")

    @commands.command()
    async def die(self, ctx):
        if ctx.voice_client:
            ctx.voice_client.stop()
        await ctx.bot.close()


bot = MyBot(command_prefix=commands.when_mentioned, intents=intents)
bot.run(TOKEN)
