# app.py (V2.2)

import streamlit as st
import re
import requests
import uuid  # 👈 新增导入
from pathlib import Path

# --- 核心应用逻辑 ---
from core.rag_engine import RAGEngine
from core.application import ResumeApplication
from config import get_config

# ===================================================================
# 辅助函数
# ===================================================================
def get_available_ollama_models(config: dict) -> list[str]:
    """
    查询Ollama API，获取可用的文本生成模型列表。
    会自动过滤掉常见的嵌入模型。
    """
    try:
        response = requests.get(f"{config['env']['ollama_host']}/api/tags")
        response.raise_for_status() # 如果请求失败则抛出异常
        
        models_data = response.json()
        model_names = [model["name"] for model in models_data.get("models", [])]
        
        # 过滤掉已知的嵌入模型关键词
        embedding_keywords = ["embed", "bge", "m3"]
        text_generation_models = [
            name for name in model_names 
            if not any(keyword in name.lower() for keyword in embedding_keywords)
        ]
        
        return sorted(text_generation_models)
    except requests.exceptions.RequestException as e:
        st.warning(f"无法连接到Ollama服务获取模型列表: {e}")
        # 如果连接失败，返回配置中的默认模型作为唯一选项
        return [config["model"]["llm_model"]]

# ===================================================================
# 应用程序状态管理
# ===================================================================
def initialize_app_state():
    """初始化或获取应用的核心组件。"""
    # 仅在 session_state 中完全没有 rag_engine 时才执行
    if "rag_engine" not in st.session_state:
        with st.spinner("首次启动，正在初始化RAG引擎..."):
            config = get_config()
            st.session_state.rag_engine = RAGEngine(config)
            st.session_state.resume_app = ResumeApplication(st.session_state.rag_engine, config)
            st.session_state.chat_history = []
            st.session_state.system_ready = True
        st.rerun()
    
    # #######################################################
    #  👇 新增：为每个会话创建一个唯一的ID
    # #######################################################
    if "session_id" not in st.session_state:
        st.session_state.session_id = str(uuid.uuid4())

# ===================================================================
# UI渲染函数
# ===================================================================
def render_sidebar():
    with st.sidebar:
        st.header("系统控制")
        
        # --- 数据摄取部分 (保持不变) ---
        st.subheader("数据摄取")
        if st.button("执行数据摄取", type="primary"):
            with st.spinner("正在清空并重建索引..."):
                # #######################################################
                #  👇 关键修复：不再依赖于修改现有对象，
                #     而是创建全新的实例来替换旧的。
                # #######################################################
                
                # 1. 获取配置
                config = get_config()

                # 2. 创建一个全新的 RAGEngine 实例
                new_engine = RAGEngine(config)
                # 明确地在其上执行重建
                new_engine.build_index(force_rebuild=True)

                # 3. 用新实例替换掉 session_state 中的旧实例
                st.session_state.rag_engine = new_engine
                st.session_state.resume_app = ResumeApplication(new_engine, config)
                
                # 4. 清空聊天历史，因为上下文已经改变
                st.session_state.resume_app.chat_histories.clear()  # 👈 清理后端历史
                st.session_state.chat_history = []
                
            st.success("数据摄取完成，应用状态已刷新！")
            # 强制页面重新运行以应用所有状态变更
            st.rerun()
            
        st.divider() # 添加分隔线

        # #######################################################
        #  👇 新增的模型选择功能
        # #######################################################
        st.subheader("🤖 模型配置")

        config = get_config()
        available_models = get_available_ollama_models(config)
        
        # 获取当前在 session_state 中存储的模型，如果没有，则使用配置文件中的默认值
        current_model = st.session_state.get("current_llm_model", config["model"]["llm_model"])

        # 创建下拉选择框
        selected_model = st.selectbox(
            "选择大语言模型 (LLM)",
            available_models,
            index=available_models.index(current_model) if current_model in available_models else 0,
            help="选择用于问答和分析的LLM。更改后，应用将重新加载模型。"
        )

        # --- 核心逻辑：当用户选择新模型时，更新状态并重新初始化 ---
        if selected_model != st.session_state.get("current_llm_model"):
            st.session_state.current_llm_model = selected_model
            
            # 创建一个新的配置字典，只覆盖llm_model
            new_config = config.copy()
            new_config["model"]["llm_model"] = selected_model
            
            # 重新初始化应用逻辑层，传入新的配置
            with st.spinner(f"正在加载模型: {selected_model}..."):
                st.session_state.resume_app = ResumeApplication(
                    st.session_state.rag_engine, 
                    new_config
                )
            st.success(f"模型已切换为: {selected_model}")
            # 最好也清空一下聊天历史，因为不同模型的回答风格可能不同
            st.session_state.resume_app.chat_histories.clear()  # 👈 清理后端历史
            st.session_state.chat_history = []
            st.rerun()

        st.divider()

        # --- 候选人选择部分 (保持不变) ---
        st.subheader("👥 候选人")
        profiles = st.session_state.rag_engine.structured_store.get_all_profiles_overview()
        candidate_names = ["- 请选择 -"] + [p["name"] for p in profiles]
        
        selected_name = st.selectbox(
            "选择查看详情", 
            candidate_names,
            key="selected_candidate_name"
        )
        st.metric("总候选人数", len(profiles))

def render_chat_interface():
    st.subheader("智能问答")
    
    # [新增] 检查是否需要因为流式输出结束而重运行
    if st.session_state.get("just_finished_streaming", False):
        st.session_state.just_finished_streaming = False
        st.rerun()

    # 显示已有的聊天历史
    for message in st.session_state.chat_history:
        with st.chat_message(message["role"]):
            if message["role"] == "assistant" and "think_content" in message and message["think_content"]:
                with st.expander("🧠 查看AI推理过程", expanded=False):
                    st.markdown(message["think_content"])
                st.markdown(message["content"])
            else:
                st.markdown(message.get("content", ""))

    # 用户输入
    if prompt := st.chat_input("请在此输入您的问题..."):
        st.session_state.chat_history.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
        
        with st.chat_message("assistant"):
            think_expander = st.expander("🧠 AI正在推理中...", expanded=True)
            think_container = think_expander.empty()
            answer_container = st.empty()
            
            think_content = ""
            answer_content = ""
            
            # #######################################################
            #  👇 核心修改：调用时传入 session_id
            # #######################################################
            response_stream = st.session_state.resume_app.ask_stream(
                prompt, 
                session_id=st.session_state.session_id
            )
            
            # 用于累积完整的响应以进行正则匹配
            accumulated_response = ""
            
            # 状态标志
            has_finished_thinking = False
            
            for chunk in response_stream:
                # 这一步很关键：有些模型即使在流式中也会一次性输出很多字符
                accumulated_response += chunk
                
                # --- 核心处理逻辑 ---
                
                # 情况1: 检测到了 </think> 结束标签
                if "</think>" in accumulated_response:
                    # 如果之前还没标记为结束思考，现在标记
                    if not has_finished_thinking:
                        has_finished_thinking = True

                    # 分割思考过程和答案
                    parts = accumulated_response.split("</think>", 1)
                    
                    # 思考部分
                    raw_think_content = parts[0]
                    think_content = raw_think_content.replace("<think>", "").strip()
                    
                    # 答案部分
                    answer_content = parts[1].strip() if len(parts) > 1 else ""
                    
                    # 更新UI内容
                    if think_content:
                        think_expander = st.expander("🧠 AI推理完成 (点击展开查看)", expanded=False)
                        think_container = think_expander.empty()
                        think_container.markdown(think_content)
                    if answer_content:
                        answer_container.markdown(answer_content)
                        
                # 情况2: 还没结束思考，但检测到了 <think> 开始标签
                elif "<think>" in accumulated_response:
                    # 只显示 <think> 之后的内容
                    think_content = accumulated_response.split("<think>", 1)[-1].strip()
                    
                    # [DEBUG] 打印实时思维链流片段
                    # 为了避免刷屏，只在内容变化明显时打印，或者简单打印长度
                    # print(f"[THINK_STREAM] Current length: {len(current_think_content)}")
                    
                    think_container.markdown(think_content)
                    
                # 情况3: 既没有 <think> 也没有 </think> (可能是纯答案，也可能是思考过程的中间部分)
                else:
                    # 这是一个模糊地带。通常如果刚开始输出且没有 <think>，
                    # 我们暂时假设它是答案，除非后续突然出现了 </think> (容错处理)
                    # 但为了体验，我们先把它显示在答案区，
                    # 如果后面突然发现是思考过程（即出现了 </think>），上面的逻辑会重写两个容器的内容
                    answer_content = accumulated_response.strip()
                    answer_container.markdown(answer_content)

            # 容错：如果模型输出了 <think> 但最终答案为空，尽量从完整响应中提取正文
            if not answer_content:
                if "</think>" in accumulated_response:
                    answer_content = accumulated_response.split("</think>", 1)[1].strip()
                elif "<think>" not in accumulated_response:
                    answer_content = accumulated_response.strip()

            # 如果仍然没有正文，给出明确提示，避免页面看起来像“丢答案”
            if not answer_content:
                answer_content = "模型本轮只返回了思考过程，没有生成最终回答。建议换一个模型重试，或调整提示词要求。"
                answer_container.markdown(answer_content)

            # [核心修改] 流结束后，不直接修改UI，而是设置一个标志并触发rerun
            st.session_state.chat_history.append({
                "role": "assistant", 
                "content": answer_content,
                "think_content": think_content
            })
            
            # 设置标志，告诉下一次运行，我们刚刚完成了流式输出
            st.session_state.just_finished_streaming = True
            
            # 立即停止当前脚本的执行，并计划一次重运行
            st.stop()

def render_overview_tab():
    st.subheader("📊 候选人概览")
    profiles = st.session_state.rag_engine.structured_store.get_all_profiles_overview()
    
    if not profiles:
        st.info("暂无候选人数据。请先点击侧边栏的'执行数据摄取'。")
        return

    # 定义推荐等级的符号映射
    def get_recommendation_icon(recommendation):
        if "强烈推荐" in recommendation:
            return "🟢"  # 绿色圆圈 - 强烈推荐
        elif "可以考虑" in recommendation:
            return "🟡"  # 黄色圆圈 - 可以考虑
        elif "不匹配" in recommendation:
            return "🔴"  # 红色圆圈 - 不匹配
        else:
            return "⚪"  # 白色圆圈 - 默认

    for profile in profiles:
        col1, col2, col3 = st.columns([4, 1, 1])
        with col1:
            st.markdown(f"**{profile['name']}**")
            st.caption(profile['summary'])
        with col2:
            st.metric("匹配度", f"{profile['overall_score']}/10")
        with col3:
            # 添加推荐等级符号
            icon = get_recommendation_icon(profile['recommendation'])
            st.markdown(f"{icon} **{profile['recommendation']}**")
        st.divider()

def render_detail_tab():
    st.subheader("📋 候选人详情")
    selected_name = st.session_state.get("selected_candidate_name")

    if not selected_name or selected_name == "- 请选择 -":
        st.info("请从侧边栏选择一位候选人查看详细报告。")
        return

    profile = st.session_state.rag_engine.structured_store.get_profile_by_name(selected_name)

    if not profile:
        st.error(f"无法加载候选人 {selected_name} 的档案。")
        return
    
    # --- UI 渲染 ---
    st.header(f"AI评估报告: {profile.name}")
    st.metric("综合匹配度", f"{profile.overall_match_score}/10", help=f"推荐等级: {profile.recommendation}")
    
    st.markdown("#### 📝 AI总结")
    st.write(profile.summary)

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("#### ✅ 优势 (Strengths)")
        for s in profile.strengths:
            st.markdown(f"- {s}")
    with col2:
        st.markdown("#### ⚠️ 关注点 (Weaknesses)")
        for w in profile.weaknesses:
            st.markdown(f"- {w}")

    with st.expander("👨‍💼 工作经历"):
        for exp in profile.work_experience:
            st.markdown(f"**{exp.position}** at **{exp.company}** (`{exp.start_date}` - `{exp.end_date or '至今'}`)")
            st.write(exp.description)
    
    with st.expander("🚀 项目经验"):
         for proj in profile.project_experience:
            st.markdown(f"**{proj.name}** ({proj.role})")
            st.write(proj.description)

def main():
    st.set_page_config(page_title="智能简历筛选系统", layout="wide")
    
    # 添加CSS样式来居中显示标题
    st.markdown("""
        <style>
        .main-header {
            text-align: center;
            margin-bottom: 2rem;
        }
        </style>
    """, unsafe_allow_html=True)
    
    # 使用HTML标签和CSS类来居中显示标题
    st.markdown('<h1 class="main-header">🤖 智能简历筛选系统</h1>', unsafe_allow_html=True)
    
    # 确保核心应用已初始化
    initialize_app_state()

    render_sidebar()
    tab1, tab2, tab3 = st.tabs(["📊 候选人概览", "📋 候选人详情", "💬 智能问答"])

    with tab1:
        render_overview_tab()
    with tab2:
        render_detail_tab()
    with tab3:
        if st.session_state.get("system_ready"):
            render_chat_interface()
        else:
            st.warning("系统正在初始化，请稍候...")

if __name__ == "__main__":
    main()
