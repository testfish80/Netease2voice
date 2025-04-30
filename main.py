import os
import base64
import re
import requests
from pkg.plugin.context import register, handler, llm_func, BasePlugin, APIHost, EventContext
from pkg.plugin.events import *  # 导入事件类
from pkg.platform.types import *
import pilk # silk 编解码
from pydub import AudioSegment
import pkg.platform.types as platform_types


def get_song_id(song_name):
    """
    根据歌曲名搜索歌曲ID，优先使用网易云音乐API，如果都是付费歌曲，则尝试QQ音乐API。
    :param song_name: 歌曲名
    :return: 歌曲ID（如果找到非付费歌曲），否则返回None
    """
    # 先尝试网易云音乐API
    netease_id = get_netease_song_id(song_name)
    if netease_id:
        return netease_id


def get_netease_song_id(song_name):
    """
    使用网易云音乐API搜索歌曲ID，跳过付费歌曲。
    :param song_name: 歌曲名
    :return: 歌曲ID（如果找到非付费歌曲），否则返回None
    """
    search_url = 'https://music.163.com/api/search/get'
    params = {
        's': song_name,
        'type': 1,  # 搜索类型为单曲
        'offset': 0,  # 从第0条结果开始
        'limit': 15  # 扩大搜索范围
    }
    try:
        response = requests.get(search_url, params=params)
        response.raise_for_status()
        data = response.json()
        if data['code'] == 200:
            if 'result' in data and 'songs' in data['result']:
                songs = data['result']['songs']
                for song in songs:
                    if song.get('fee', 0) == 0:  # fee为0表示免费歌曲
                        return song['id']
                print("网易云音乐：找到的歌曲均为付费歌曲，跳过。")
    except requests.exceptions.HTTPError as http_err:
        print(f'网易云音乐API请求失败: {http_err}')
    except Exception as err:
        print(f'网易云音乐API发生错误: {err}')
    return None


def get_song_url(song_id):
    """
    根据歌曲ID获取歌曲的直链。
    :param song_id: 歌曲ID
    :return: 歌曲直链（如果找到），否则返回None
    """
    url = f'https://music.163.com/song/media/outer/url?id={song_id}.mp3'
    try:
        response = requests.get(url, allow_redirects=False)  # 禁止重定向
        response.raise_for_status()  # 检查请求是否成功
        if response.status_code == 302:  # 如果是重定向响应
            return response.headers['Location']  # 返回重定向后的直链
    except requests.exceptions.HTTPError as http_err:
        print(f'HTTP error occurred: {http_err}')
    except Exception as err:
        print(f'An error occurred: {err}')
    return None  # 如果获取失败，返回None

def download_song(url, directory, filename):
    """
    下载歌曲并保存为MP3文件到指定目录。
    :param url: 歌曲直链
    :param directory: 保存的目录
    :param filename: 保存的文件名
    :return: True if download is successful, False otherwise.
    """
    try:
        response = requests.get(url, stream=True) # 使用 stream=True
        response.raise_for_status()  # 检查请求是否成功
        os.makedirs(directory, exist_ok=True)  # 创建目录（如果不存在）
        file_path = os.path.join(directory, filename)
        with open(file_path, 'wb') as f:  # 以二进制写入模式打开文件
            for chunk in response.iter_content(chunk_size=8192): # 分块写入
                f.write(chunk)
        print(f"歌曲已下载并保存为 {file_path}")
        return True  # 下载成功
    except requests.exceptions.HTTPError as http_err:
        print(f'HTTP error occurred: {http_err}')
        return False  # 下载失败
    except Exception as err:
        print(f'An error occurred: {err}')
        return False  # 下载失败



def mp3_to_silk(mp3_file, ffmpeg_path, encoder_path, silk_file_path):
    import subprocess

    mp3_file = r"{}".format(mp3_file)
    ffmpeg_path = r"{}".format(ffmpeg_path)
    encoder_path = r"{}".format(encoder_path)
    silk_file_path = r"{}".format(silk_file_path)

    try:
        subprocess.run([
            ffmpeg_path,
            '-y',
            '-i', mp3_file,
            '-f', 's16le',
            '-ar', '24000',
            '-ac', '1',
            'temp.pcm'
        ], check=True)

        subprocess.run([
            encoder_path,
            'temp.pcm',
            silk_file_path,
            '-rate', '24000',
            '-tencent'
        ], check=True)
    except subprocess.CalledProcessError:
        return None

    return silk_file_path
    
def convert_to_silk(media_path: str, silk_file_path: str) -> str:
    """将输入的媒体文件转出为 silk, 并返回silk路径 (使用 pilk 库)"""
    media_path = r"{}".format(media_path)
    silk_file_path = r"{}".format(silk_file_path)

    try:
        # 1. 加载音频文件
        media = AudioSegment.from_file(media_path)

        # 2.  创建临时 PCM 文件
        pcm_path = "temp.pcm"

        # 3. 导出为 PCM 格式
        media.export(pcm_path, format="s16le", parameters=["-ac", "1", "-ar", str(media.frame_rate)]).close()

        # 4. 使用 pilk 编码
        pilk.encode(pcm_path, silk_file_path, pcm_rate=media.frame_rate, tencent=True)

        # 5. 删除临时 PCM 文件
        os.remove(pcm_path)

        return silk_file_path

    except FileNotFoundError:
        print("文件未找到")
        return None
    except Exception as e:
        print(f"发生其他错误: {e}")
        return None


@register(name="Netease_get", description="点歌", version="1.2", author="GryllsGYS")
class MyPlugin(BasePlugin):

    # 插件加载时触发
    def __init__(self, host: APIHost):
        pass

    # 异步初始化
    async def initialize(self):
        pass

    @handler(PersonNormalMessageReceived)
    async def person_normal_message_received(self, ctx: EventContext):

        msg: str = ctx.event.text_message  # 这里的 event 即为 PersonNormalMessageReceived 的对象
        match = re.search(r'(.*)(点歌)(.*)', msg)
        if match:
            ctx.prevent_default()
            song_name = match.group(3)
            song_id = get_song_id(song_name)
            if song_id:
                song_url = get_song_url(song_id)
                if song_url:
                    download_dir = os.path.join(
                        os.path.dirname(__file__), 'music')
                    
                    # 读取silk文件并以base64格式发送
                    download_success = download_song(song_url, download_dir, f'{song_name}.mp3') # 获取返回值
                    if download_success: # 检查下载是否成功
                        mp3_path = os.path.join(os.path.dirname(
                            __file__), 'music', f'{song_name}.mp3')
                        silk_path = os.path.join(os.path.dirname(
                            __file__), 'music', f'{song_name}.silk')
                        # 将mp3转换为silk
                        # path = mp3_to_silk(mp3_path, ffmpeg_path,
                        #                    encoder_path, silk_path)
                        path = convert_to_silk(mp3_path,silk_path)

                        print(path)
                        if path is None:
                            await ctx.send_message("person", ctx.event.sender_id, [Plain("未找到该歌曲")])
                            os.remove(os.path.join(
                                download_dir, f'{song_name}.mp3'))
                            
                         # 读取silk文件并以base64格式发送
                        with open(path, "rb")as f:
                            base64_audio = base64.b64encode(f.read()).decode()
                            await ctx.send_message("person", ctx.event.sender_id, [Voice(base64=base64_audio)])
                        # os.remove(os.path.join(download_dir, f'{song_name}.mp3'))
                        # os.remove(os.path.join(download_dir, f'{song_name}.silk'))
                    else:
                        await ctx.send_message("person", ctx.event.sender_id, [Plain("下载歌曲失败")])
                else:
                    await ctx.send_message("person", ctx.event.sender_id, [Plain("获取歌曲链接失败")])
            else:
                await ctx.send_message("person", ctx.event.sender_id, [Plain("未找到该歌曲")])

        if msg == "乓啪咔乓乓乓":
            # 阻止默认处理
            ctx.prevent_default()
            # 读取silk文件并转成base64
            path = os.path.join(os.path.dirname(__file__),
                                "voice", "200.silk")
            # with open(path, "rb") as f:
            #     base64_audio = base64.b64encode(f.read()).decode()
            if os.path.exists(path):
                # voice = await MessageChain([Voice.from_local(filename=path)
                #                            ])
                try:
                    with open(path, "rb") as f:
                        audio_data = f.read()
                    audio_base64 = base64.b64encode(audio_data).decode("utf-8")
                    voice_message = MessageChain([Voice(url=f"data:audio/mpeg;base64,{audio_base64}")]) # 创建MessageChain
                    msg_chain = MessageChain([
                        Plain("Hello LangBot")
                                         ])
                    await ctx.send_message("person", ctx.event.sender_id,msg_chain)
                    # 发送语音消息
                    # await ctx.send_message("person", ctx.event.sender_id,[Voice(path=str(path))])
                    await ctx.send_message("person", ctx.event.sender_id, voice_message)
                except Exception as e:
                    self.ap.logger.error(f"发送语音消息失败: {e}") # 使用ctx.ap.logger记录错误
                 
        if msg == "唱歌":
            # 阻止默认处理
            ctx.prevent_default()
            # 读取silk文件并转成base64
            path = os.path.join(os.path.dirname(__file__),
                                "voice", "sing.silk")
            with open(path, "rb") as f:
                base64_audio = base64.b64encode(f.read()).decode()
                # 发送语音消息
                await ctx.send_message("person", ctx.event.sender_id, [Voice(base64=base64_audio)])

    @handler(GroupNormalMessageReceived)
    async def group_normal_message_received(self, ctx: EventContext):

        msg: str = ctx.event.text_message  # 这里的 event 即为 PersonNormalMessageReceived 的对象
        match = re.search(r'(.*)(点歌)(.*)', msg)
        if match:
            ctx.prevent_default()
            song_name = match.group(3)
            song_id = get_song_id(song_name)
            if song_id:
                song_url = get_song_url(song_id)
                if song_url:
                    download_dir = os.path.join(
                        os.path.dirname(__file__), 'music')
                    download_song(song_url, download_dir, f'{song_name}.mp3')
                    mp3_path = os.path.join(os.path.dirname(
                        __file__), 'music', f'{song_name}.mp3')
                    silk_path = os.path.join(os.path.dirname(
                        __file__), 'music', f'{song_name}.silk')
                    # 将mp3转换为silk
                    # path = mp3_to_silk(mp3_path, ffmpeg_path,
                    #                    encoder_path, silk_path)
                    path = convert_to_silk(mp3_path)
                    print(path)
                    if path is None:
                        await ctx.send_message("group", ctx.event.launcher_id, [Plain("未找到该歌曲")])
                        os.remove(os.path.join(
                            download_dir, f'{song_name}.mp3'))
                    # 读取silk文件并以base64格式发送
                    with open(path, "rb")as f:
                        base64_audio = base64.b64encode(f.read()).decode()
                        await ctx.send_message("group", ctx.event.launcher_id, [Voice(base64=base64_audio)])

                    os.remove(os.path.join(download_dir, f'{song_name}.mp3'))
                    os.remove(os.path.join(download_dir, f'{song_name}.silk'))
                else:
                    await ctx.send_message("group", ctx.event.launcher_id, [Plain("获取歌曲链接失败")])
            else:
                await ctx.send_message("group", ctx.event.launcher_id, [Plain("未找到该歌曲")])
         # 如果收到"乓啪咔乓乓乓"
        if msg == "乓啪咔乓乓乓":
            ctx.prevent_default()
            path = os.path.join(os.path.dirname(__file__),
                                "voice", "200.silk")
            with open(path, "rb") as f:
                base64_audio = base64.b64encode(f.read()).decode()
                await ctx.send_message("group", ctx.event.launcher_id, [Voice(base64=base64_audio)])

        if msg == "唱歌":
            ctx.prevent_default()
            path = os.path.join(os.path.dirname(__file__),
                                "voice", "sing.silk")
            with open(path, "rb") as f:
                base64_audio = base64.b64encode(f.read()).decode()
                await ctx.send_message("group", ctx.event.launcher_id, [Voice(base64=base64_audio)])

    def __del__(self):
        pass
