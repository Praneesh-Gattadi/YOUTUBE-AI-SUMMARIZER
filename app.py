import streamlit as st
import os
import zipfile
import io
from dotenv import load_dotenv

from summarizer import (
    generate_article, 
    generate_webpage, 
    parse_webpage_output
)

load_dotenv()

st.set_page_config(page_title="Gemini YouTube Summarizer", page_icon="🎬", layout="wide")

# Custom CSS for Premium UI/UX
st.markdown("""
    <style>
        /* Import premium font */
        @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;800&display=swap');
        
        /* Global Font Override */
        html, body, [class*="css"]  {
            font-family: 'Outfit', sans-serif;
        }
        
        /* Main Title Styling */
        .main-hero {
            text-align: center;
            padding: 2rem 0;
            background: linear-gradient(90deg, #ff416c 0%, #ff4b2b 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            font-size: 3rem;
            font-weight: 800;
            margin-bottom: 0.5rem;
        }
        
        .sub-hero {
            text-align: center;
            color: #a0a0b0;
            font-size: 1.1rem;
            margin-bottom: 3rem;
        }

        /* Input Field Styling */
        div[data-baseweb="input"] {
            border-radius: 12px;
            background-color: rgba(255, 255, 255, 0.05);
            border: 1px solid rgba(255, 255, 255, 0.1);
            transition: all 0.3s ease;
        }
        div[data-baseweb="input"]:focus-within {
            border-color: #ff416c;
            box-shadow: 0 0 15px rgba(255, 65, 108, 0.2);
        }

        /* Button Styling */
        button[kind="primary"] {
            background: linear-gradient(90deg, #ff416c 0%, #ff4b2b 100%) !important;
            border: none !important;
            border-radius: 12px !important;
            font-weight: 600 !important;
            letter-spacing: 0.5px !important;
            transition: all 0.3s ease !important;
        }
        button[kind="primary"]:hover {
            transform: translateY(-2px);
            box-shadow: 0 8px 20px rgba(255, 65, 108, 0.3) !important;
        }

        /* Tabs Styling */
        button[data-baseweb="tab"] {
            background-color: transparent !important;
            border-radius: 8px 8px 0 0 !important;
            font-weight: 600 !important;
        }
        div[data-baseweb="tab-list"] {
            gap: 1rem;
        }

        /* Download Button */
        button[kind="secondary"] {
            border-radius: 12px !important;
            border: 1px solid rgba(255, 255, 255, 0.2) !important;
            transition: all 0.3s ease !important;
        }
        button[kind="secondary"]:hover {
            border-color: #fff !important;
            background-color: rgba(255, 255, 255, 0.1) !important;
        }
    </style>
""", unsafe_allow_html=True)

st.markdown('<h1 class="main-hero">🎬 YouTube Article Generator</h1>', unsafe_allow_html=True)
st.markdown('<p class="sub-hero">Instantly transform any long-form video into a premium blog post and fully coded web page.</p>', unsafe_allow_html=True)

# Initialize session state for multi-user isolation on AWS
if "google_api_key" not in st.session_state:
    st.session_state.google_api_key = os.getenv("GOOGLE_API_KEY") # Initial fallback
    # Clear global ENV to prevent other sessions from seeing this one
    if os.getenv("GOOGLE_API_KEY"):
        os.environ["GOOGLE_API_KEY"] = ""

with st.sidebar:
    st.header("⚙️ Configuration")
    
    # Check if we have a key in the current session
    current_key = st.session_state.google_api_key
    
    if not current_key or "your_" in current_key:
        user_key = st.text_input("Enter Gemini API Key", type="password")
        if user_key:
            st.session_state.google_api_key = user_key
            st.success("API Key updated for this session!")
            st.rerun()
    else:
        st.success("✅ Gemini API Key Found (Session Active)")
        if st.button("Change API Key"):
            st.session_state.google_api_key = ""
            st.rerun()

    model_name = st.selectbox("Select Gemini Model", ["gemini-2.0-flash", "gemini-2.5-flash", "gemini-2.5-pro"], index=0)
    
    if not os.path.exists("cookies.txt"):
        st.divider()
        st.markdown("**🛡️ Server Authorization Required**")
        uploaded_cookies = st.file_uploader("Upload cookies.txt file", type=["txt"], help="Admin Only: Upload cookies to bypass AWS IP blocks permanently.")
        if uploaded_cookies:
            with open("cookies.txt", "wb") as f:
                f.write(uploaded_cookies.getbuffer())
            st.success("✅ Server Authorized! Please refresh the page. This box will now disappear for all users.")

youtube_url = st.text_input("Enter YouTube URL", placeholder="https://youtu.be/...")
generate_clicked = st.button("🚀 Generate Content", use_container_width=True, type="primary")

if generate_clicked:
    if not youtube_url:
        st.error("Please enter a URL.")
    elif not st.session_state.google_api_key:
        st.error("Please provide a Gemini API Key in the sidebar.")
    else:
        try:
            with st.status("🚀 Initializing AI Engine...", expanded=True) as status:
                status.write("⏳ Extracting audio and summarizing content...")
                article_content = generate_article(
                    youtube_url, 
                    model_name=model_name, 
                    api_key=st.session_state.google_api_key
                )
            
                status.write("🎨 Designing premium webpage layouts...")
                webpage_response = generate_webpage(
                    article_content, 
                    model_name=model_name,
                    api_key=st.session_state.google_api_key
                )
                codes = parse_webpage_output(webpage_response)

                status.update(label="✅ Content Generated Successfully!", state="complete", expanded=False)

            tab1, tab2, tab3, tab4 = st.tabs(["🖥️ Live Preview", "📄 Raw ArticleText", "💻 Code", "📦 Download"])
            with tab1:
                with st.container():
                    # Fuse CSS into HTML <style> for proper component rendering
                    fused_html = f"""
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <style>{codes.get('css', '')}</style>
                        <script>{codes.get('js', '')}</script>
                    </head>
                    <body>
                        {codes.get('html', '')}
                    </body>
                    </html>
                    """
                    import streamlit.components.v1 as components
                    components.html(fused_html, height=700, scrolling=True)
            with tab2: 
                st.markdown(article_content)
            with tab3:
                st.code(codes.get("html", ""), language="html")
                st.code(codes.get("css", ""), language="css")
            with tab4:
                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, 'w') as zf:
                    zf.writestr("index.html", codes.get("html", ""))
                    zf.writestr("style.css", codes.get("css", ""))
                st.download_button("📥 Download ZIP", data=zip_buffer.getvalue(), file_name="gemini_web.zip")
        except Exception as e:
            st.error(f"Error: {e}")
