import discord
from discord.ext import commands, voice_recv
from dotenv import load_dotenv
import os
import subprocess
import datetime
import time
import whisper

load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")

intents = discord.Intents.default()
intents.message_content = True

discord.opus._load_default()

# 유저별 음성 데이터를 저장할 딕셔너리
# 구조: { user_id: {'name': user_name, 'chunks': [(timestamp, audio_chunk), ...] } }
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
        각 청크마다 녹음 시각과 사용자 이름을 함께 저장합니다.
        """

        def callback(user, data: voice_recv.VoiceData):
            print(f"Got packet from {user}")
            # PCM 데이터를 사용
            audio_bytes = data.pcm
            timestamp = time.time()  # 현재 시각 (epoch seconds)
            if user.id not in user_voice_data:
                user_voice_data[user.id] = {"name": user.name, "chunks": []}
            user_voice_data[user.id]["chunks"].append((timestamp, audio_bytes))

        if ctx.author.voice and ctx.author.voice.channel:
            vc = await ctx.author.voice.channel.connect(cls=voice_recv.VoiceRecvClient)
            vc.listen(voice_recv.BasicSink(callback))
            await ctx.send("음성 데이터를 수신하기 시작합니다.")
        else:
            await ctx.send("먼저 음성 채널에 들어가주세요!")

    @commands.command()
    async def play(self, ctx):
        """
        저장된 음성 데이터를 불러와 임시 파일에 저장 후, 음성 채널에서 재생합니다.
        여기서는 명령어를 실행한 유저의 데이터를 사용합니다.
        """
        if (
            ctx.author.id not in user_voice_data
            or not user_voice_data[ctx.author.id]["chunks"]
        ):
            await ctx.send("저장된 음성 데이터가 없습니다.")
            return

        chunks = sorted(user_voice_data[ctx.author.id]["chunks"], key=lambda x: x[0])
        combined_audio = b"".join(chunk for (_, chunk) in chunks)
        raw_filename = f"{ctx.author.id}_voice.raw"
        with open(raw_filename, "wb") as f:
            f.write(combined_audio)

        await ctx.send("저장된 음성 데이터를 사용합니다.")

        if ctx.voice_client is None:
            if ctx.author.voice and ctx.author.voice.channel:
                vc = await ctx.author.voice.channel.connect()
            else:
                await ctx.send("음성 채널에 접속해주세요!")
                return
        else:
            vc = ctx.voice_client

        # before_options를 사용하여 FFmpeg에게 raw PCM 포맷임을 알림
        source = discord.FFmpegPCMAudio(
            raw_filename, before_options="-f s16le -ar 48000 -ac 2"
        )
        vc.play(source)

    @commands.command()
    async def transcribe(self, ctx):
        """
        저장된 음성 데이터를 OpenAI Whisper로 텍스트로 변환합니다.
        각 유저의 발화는 녹음 시작 시각(offset)과 Whisper의 상대 시간 정보를 더해 실제 시각으로 변환됩니다.
        이후 여러 유저의 발화를 실제 시간 순으로 정렬하여 대화 형태로 출력합니다.
        """
        if not user_voice_data:
            await ctx.send("저장된 음성 데이터가 없습니다.")
            return

        await ctx.send(
            "Whisper를 사용하여 음성 데이터를 텍스트로 변환 중입니다. 잠시만 기다려주세요..."
        )
        model = whisper.load_model("base")
        all_segments = (
            []
        )  # 각 발화: { 'start': 실제 시작시간, 'end': 실제 종료시간, 'user': 사용자, 'text': 전사 내용 }

        for user_id, data_dict in user_voice_data.items():
            user_name = data_dict["name"]
            chunks = sorted(data_dict["chunks"], key=lambda x: x[0])
            offset = chunks[0][0]  # 해당 유저의 녹음 시작 시각 (epoch seconds)
            combined_audio = b"".join(chunk for (_, chunk) in chunks)
            raw_filename = f"{user_id}_voice.raw"
            wav_filename = f"{user_id}_voice.wav"
            with open(raw_filename, "wb") as f:
                f.write(combined_audio)

            # raw PCM 파일을 WAV로 변환 (ffmpeg)
            ffmpeg_cmd = [
                "ffmpeg",
                "-y",
                "-f",
                "s16le",
                "-ar",
                "48000",
                "-ac",
                "2",
                "-i",
                raw_filename,
                wav_filename,
            ]
            subprocess.run(ffmpeg_cmd, check=True)

            result = model.transcribe(wav_filename)
            for segment in result["segments"]:
                # Whisper의 시간은 파일 시작 기준이므로 offset을 더해 실제 시간으로 변환
                actual_start = offset + segment["start"]
                actual_end = offset + segment["end"]
                # 실제 시간을 HH:MM:SS 형식으로 변환
                start_str = datetime.datetime.fromtimestamp(actual_start).strftime(
                    "%H:%M:%S"
                )
                end_str = datetime.datetime.fromtimestamp(actual_end).strftime(
                    "%H:%M:%S"
                )
                text = segment["text"].strip()
                all_segments.append(
                    {
                        "start": actual_start,
                        "end": actual_end,
                        "user": user_name,
                        "start_str": start_str,
                        "end_str": end_str,
                        "text": text,
                    }
                )

        # 모든 유저의 발화를 실제 시작 시간 순으로 정렬
        all_segments.sort(key=lambda x: x["start"])
        final_transcription = "Transcription:\n"
        for segment in all_segments:
            final_transcription += f"[{segment['start_str']} - {segment['end_str']}] **{segment['user']}**: {segment['text']}\n"
        await ctx.send(final_transcription)

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
