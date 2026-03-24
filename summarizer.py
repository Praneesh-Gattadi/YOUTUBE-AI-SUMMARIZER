import os
import time
import math
import tempfile
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_community.document_loaders import YoutubeLoader

load_dotenv()

def get_llm(model_name="gemini-2.0-flash"):
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key or "your_" in api_key:
        raise ValueError("GOOGLE_API_KEY not found. Please check your .env or sidebar.")
    return ChatGoogleGenerativeAI(model=model_name, google_api_key=api_key)

def extract_transcript(link: str, model_name="gemini-2.0-flash") -> str:
    import yt_dlp
    from google import genai
    
    import subprocess, sys
    # 0. Self-Healing Upgrades and Diagnostics
    try:
        # Upgrade yt-dlp dynamically to bypass signature solver deprecations
        subprocess.run([sys.executable, "-m", "pip", "install", "-U", "yt-dlp"], capture_output=True, timeout=30)
    except Exception:
        pass

    def check_bin(name):
        try:
            res = subprocess.run([name, '--version'], capture_output=True, text=True)
            return f"{name}: {res.stdout.strip() or 'No version output'}"
        except Exception:
            try:
                # Some binaries respond to -version
                res = subprocess.run([name, '-version'], capture_output=True, text=True)
                return f"{name}: {res.stdout.strip() or 'No version output'}"
            except Exception:
                return f"{name}: NOT FOUND"
                
    node_status = check_bin('node')
    if "NOT FOUND" in node_status:
        return f"ERROR: [Environment Fix Required] Node.js is STILL missing. Please run 'sudo apt update && sudo apt install -y nodejs npm' on your AWS terminal to solve YouTube's encryption."

    video_id = get_video_id(link)
    
    # 1. Custom Session Transcript API
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        from youtube_transcript_api.formatters import TextFormatter
        import requests
        import http.cookiejar
        
        session = requests.Session()
        # Add standard headers to look like a desktop browser
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        })
        
        if os.path.exists("cookies.txt"):
            from requests.cookies import RequestsCookieJar
            jar = RequestsCookieJar()
            cookie_count = 0
            with open("cookies.txt", 'r') as f:
                for line in f:
                    if line.startswith("#") and not line.startswith("#HttpOnly_"): continue
                    curr_line = line[10:] if line.startswith("#HttpOnly_") else line
                    if not curr_line.strip(): continue
                    parts = curr_line.strip().split("\t")
                    if len(parts) >= 7:
                        domain = parts[0]
                        path = parts[2]
                        name = parts[5]
                        value = parts[6]
                        if "youtube.com" in domain or "google.com" in domain:
                            # Standardize domain for requests
                            dom_sub = f".{domain.lstrip('.')}" if domain.startswith(".") else domain
                            if not dom_sub.startswith("."): dom_sub = f".{dom_sub}"
                            jar.set(name, value, domain=dom_sub, path=path)
                            cookie_count += 1
            if cookie_count > 0:
                session.cookies.update(jar)
        try:
            api = YouTubeTranscriptApi(http_client=session)
            transcript_list = api.list(video_id)
            transcript = transcript_list.find_transcript(['en'])
            text = TextFormatter().format_transcript(transcript.fetch())
            
            if len(text) > 100:
                return text
        except Exception:
            pass
    except Exception:
        pass
    
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            # 2. Try Subtitles
            try:
                ydl_opts = {
                    'skip_download': True, 'writesubtitles': True, 'writeautomaticsub': True, 
                    'subtitleslangs': ['en'], 'outtmpl': os.path.join(temp_dir, "%(id)s.%(ext)s"), 'quiet': True,
                    'extractor_args': {'youtube': {'client': ['ios', 'android', 'web']}}
                }
                if os.path.exists("cookies.txt"): ydl_opts['cookiefile'] = 'cookies.txt'
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([link])

                vtt_path = os.path.join(temp_dir, f"{video_id}.en.vtt")
                if os.path.exists(vtt_path):
                    with open(vtt_path, 'r', encoding='utf-8') as f:
                        return clean_vtt(f.read())
            except Exception:
                # If subtitles fail (e.g. 429 Rate Limit), ignore and cascade to Audio download below
                pass

            # 3. Audio Processing with Chunking Fallback
            audio_path_base = os.path.join(temp_dir, "audio")
            # Down-mux locally via FFmpeg to bypass YouTube removing 'bestaudio' from AWS datacenter manifests
            ydl_opts_audio = {
                'format': 'bestaudio/bestvideo+bestaudio/18/139/140/249/251/worst', 
                'outtmpl': f"{audio_path_base}.%(ext)s", 
                'quiet': True,
                'extractor_args': {'youtube': {'client': ['ios', 'android', 'web']}},
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'm4a',
                }]
            }
            if os.path.exists("cookies.txt"): ydl_opts_audio['cookiefile'] = 'cookies.txt'
            ydl_opts_audio['listformats'] = True # Force table generation
            
            import io, contextlib
            f_out = io.StringIO()
            try:
                with contextlib.redirect_stdout(f_out):
                    with yt_dlp.YoutubeDL(ydl_opts_audio) as ydl:
                        ydl.download([link])
            except Exception:
                pass
            
            table_output = f_out.getvalue()
            is_blocked = "m4a" not in table_output and "mp4" not in table_output
            
            if is_blocked:
                # 4. Proxy Fallback Trigger
                import requests
                try:
                    proxy_url = "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=3000"
                    res = requests.get(proxy_url, timeout=5)
                    proxies = [p.strip() for p in res.text.split('\n') if p.strip()]
                except Exception:
                    proxies = []
                    
                if proxies:
                    for proxy in proxies[:15]: # Test top 15
                        test_opts = {
                            'format': 'bestaudio/bestvideo+bestaudio/18/140/worst',
                            'outtmpl': f"{audio_path_base}.%(ext)s", 
                            'quiet': True,
                            'proxy': f"http://{proxy}",
                            'socket_timeout': 5, # Skip slow/dead proxies quickly
                            'extractor_args': {'youtube': {'client': ['ios', 'android']}},
                            'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'm4a'}]
                        }
                        try:
                            with yt_dlp.YoutubeDL(test_opts) as ydl_p:
                                ydl_p.download([link])
                            # If download succeeds, break out
                            files_p = [f for f in os.listdir(temp_dir) if f.startswith("audio")]
                            if files_p:
                                break
                        except Exception:
                            continue
                
                # Check if proxy saved us
                files_check = [f for f in os.listdir(temp_dir) if f.startswith("audio")]
                if not files_check:
                    raise Exception(f"Datacenter Blocked! Zero media tracks pulled. Proxies tested: {len(proxies[:15])}. \nDetails:\n{table_output}")
            else:
                # Case where formats DO exist but download didn't run because of listformats=True
                # Remove 'listformats' and run standard download
                del ydl_opts_audio['listformats']
                with yt_dlp.YoutubeDL(ydl_opts_audio) as ydl_final:
                    ydl_final.download([link])

            files = [f for f in os.listdir(temp_dir) if f.startswith("audio")]
            if not files: raise Exception("Audio download failed.")
            actual_audio_path = os.path.join(temp_dir, files[0])

            # Gemini File Processing
            client = genai.Client(
                api_key=os.getenv("GOOGLE_API_KEY"),
                http_options={'timeout': 600000} # 10 minutes for large audio files
            )
            uploaded_file = client.files.upload(file=actual_audio_path)
            
            # Wait with backoff
            wait_time = 0
            while uploaded_file.state.name == "PROCESSING":
                if wait_time > 400: raise Exception("Gemini processing timeout.")
                time.sleep(15)
                wait_time += 15
                uploaded_file = client.files.get(name=uploaded_file.name)
            
            if uploaded_file.state.name == "FAILED":
                # If a large file fails, provide a clear instruction to the user
                raise Exception("The video is too long for the current API limits. Please try a video under 20 minutes.")

            response = client.models.generate_content(
                model=model_name,
                contents=[
                    uploaded_file, 
                    "Please provide a highly detailed, comprehensive chronological summary of this entire audio file. "
                    "Since raw transcriptions of long forms exceed output limits, extract all the spoken content, main ideas, "
                    "arguments, decisions, and structural sections in extreme detail so that no important context is lost."
                ]
            )
            
            try: client.files.delete(name=uploaded_file.name)
            except: pass
            return response.text

    except Exception as e:
        if "500" in str(e):
            return "ERROR: Gemini is currently overloaded. Please try again in a few minutes or use a shorter video."
        raise e

def get_video_id(url: str):
    import re
    ids = re.findall(r'(?:v=|\/)([a-zA-Z0-9_-]{11})', url)
    return ids[0] if ids else "video"

def clean_vtt(vtt_content):
    import re
    lines = vtt_content.split('\n')
    cleaned = []
    for line in lines:
        line = line.strip()
        if not line or "WEBVTT" in line or "-->" in line or re.match(r'^\d+$', line): continue
        if not cleaned or cleaned[-1] != line: cleaned.append(line)
    return ' '.join(cleaned)

def generate_article_from_text(transcript_text, model_name="gemini-2.0-flash"):
    llm = get_llm(model_name)
    prompt = ChatPromptTemplate.from_messages([
        ("system", "You are an AI research assistant."),
        ("user", "Summarize this into a professional technical article:\n\n{transcript}")
    ])
    return (prompt | llm | StrOutputParser()).invoke({"transcript": transcript_text})

def generate_article(youtube_url, model_name="gemini-2.0-flash"):
    transcript = extract_transcript(youtube_url, model_name)
    if transcript.startswith("ERROR:"): return transcript
    return generate_article_from_text(transcript, model_name)

def generate_webpage(article_content, model_name="gemini-2.0-flash"):
    llm = get_llm(model_name)
    prompt = ChatPromptTemplate.from_messages([
        ("system", (
            "You are a master Web Designer and Front-End Developer. Use exact structure strings. "
            "Wrap your output sections exclusively inside: --html-- [code] --html--, --css-- [code] --css--, --js-- [code] --js-- tags. "
            "Do NOT use markdown code fences inside the tags."
        )),
        ("user", (
            "Create an extremely beautiful, elegant, and premium responsive article webpage for this content:\n\n"
            "{article_content}\n\n"
            "**Design Guidelines:**\n"
            "1. **Aesthetics:** Elegant dark mode theme or vibrant modern gradients, glassmorphism, smooth micro-animations on hover.\n"
            "2. **Typography:** Use gorgeous clean fonts (e.g., 'Outfit', 'Inter', or 'Poppins' from Google Fonts).\n"
            "3. **Layout:** Split it into descriptive components: Hero Cover/Header, Sticky Navigation outline, Floating reading progress, and fully readable grid spacing paragraphs.\n"
            "4. **Details:** Include clean margins, legible font scales, and soft shadows."
        ))
    ])
    return (prompt | llm | StrOutputParser()).invoke({'article_content': article_content})

def parse_webpage_output(response_text):
    result = {"html": "", "css": "", "js": ""}
    import re
    for lang in ["html", "css", "js"]:
        # Match --lang-- ... content ... --lang-- OR just --lang-- and till end/next tag
        pattern = f"--{lang}--(.*?)--{lang}--"
        match = re.search(pattern, response_text, re.DOTALL)
        if match:
             result[lang] = match.group(1).strip()
        else:
             # Fallback to standard split if closing tag is missing
             tag = f"--{lang}--"
             if tag in response_text:
                  parts = response_text.split(tag)
                  if len(parts) > 1:
                       result[lang] = parts[1].split("--")[0].strip() # stop at next tag divider
    return result
