"use client";

import { type FormEvent, type ReactNode, useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  DatabaseZap,
  Bot,
  BriefcaseBusiness,
  ChevronDown,
  ChevronUp,
  Download,
  ExternalLink,
  FileSearch,
  FileText,
  KeyRound,
  Loader2,
  LogOut,
  MessageSquareText,
  MonitorCheck,
  Route,
  Search,
  Send,
  Sparkles,
  Trash2,
  Upload,
  UserRound,
  X,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  CandidateDetail,
  CandidateListItem,
  ClassifiedProjects,
  EducationExperience,
  Project,
  ResumeDocument,
  SummaryResponse,
  Tag,
  WorkExperience,
  WorkProfile,
  QAAskResponse,
  QAEvidenceRef,
  askResumeQa,
  clearAccessToken,
  clearResumeData,
  generateCandidateSummary,
  getAccessToken,
  getCandidateDetail,
  getCandidateProjects,
  getCandidateResumeDocument,
  getCandidates,
  getIngestionStatus,
  getLlmStatus,
  ingestResumeFiles,
  IngestionResponse,
  IngestionResult,
  IngestionStatus,
  LlmStatus,
  setAccessToken,
  toApiUrl,
  uploadResumeFile,
} from "@/lib/api";

type ActiveView = "candidates" | "qa";

type QAChatMessage = {
  id: string;
  role: "user" | "assistant";
  text: string;
  response?: QAAskResponse;
};

export default function HomePage() {
  const [activeView, setActiveView] = useState<ActiveView>("candidates");
  const [candidates, setCandidates] = useState<CandidateListItem[]>([]);
  const [selectedIdentity, setSelectedIdentity] = useState("");
  const [candidate, setCandidate] = useState<CandidateDetail | null>(null);
  const [projects, setProjects] = useState<ClassifiedProjects | null>(null);
  const [resumeDocument, setResumeDocument] = useState<ResumeDocument | null>(null);
  const [summary, setSummary] = useState<SummaryResponse | null>(null);
  const [keyword, setKeyword] = useState("");
  const [loading, setLoading] = useState(false);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [ingesting, setIngesting] = useState(false);
  const [ingestMessage, setIngestMessage] = useState("");
  const [ingestDetails, setIngestDetails] = useState<string[]>([]);
  const [ingestStatus, setIngestStatus] = useState<IngestionStatus | null>(null);
  const [ingestionFeedbackHidden, setIngestionFeedbackHidden] = useState(false);
  const [refreshingCandidates, setRefreshingCandidates] = useState(false);
  const [llmStatus, setLlmStatus] = useState<LlmStatus | null>(null);
  const [llmChecking, setLlmChecking] = useState(false);
  const [error, setError] = useState("");
  const [qaQuestion, setQaQuestion] = useState("");
  const [qaMessages, setQaMessages] = useState<QAChatMessage[]>([]);
  const [qaSessionContext, setQaSessionContext] = useState<Record<string, unknown>>({});
  const [qaLoading, setQaLoading] = useState(false);
  const [qaError, setQaError] = useState("");
  const [qaUseLlm, setQaUseLlm] = useState(true);
  const [qaDebug, setQaDebug] = useState(false);
  const [qaAdvancedDebug, setQaAdvancedDebug] = useState(false);
  const [authRequired, setAuthRequired] = useState(false);
  const [accessTokenPresent, setAccessTokenPresent] = useState(false);
  const [passwordInput, setPasswordInput] = useState("");
  const [authChecking, setAuthChecking] = useState(false);
  const loadSeq = useRef(0);
  const ingestingRef = useRef(false);
  const ingestPollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const uploadInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    setAccessTokenPresent(Boolean(getAccessToken()));
    void loadCandidates();
  }, []);

  useEffect(() => {
    if (!selectedIdentity) return;
    void loadCandidate(selectedIdentity);
  }, [selectedIdentity]);

  function reportError(err: unknown, setter: (value: string) => void = setError) {
    const message = normalizeError(err);
    if (isUnauthorizedError(err)) {
      clearAccessToken();
      setAuthRequired(true);
      setter("请输入访问密码后继续。");
      return;
    }
    setter(message);
  }

  async function loadCandidates() {
    setLoading(true);
    setError("");
    try {
      const payload = await getCandidates();
      setCandidates(payload.candidates || []);
    } catch (err) {
      reportError(err);
    } finally {
      setLoading(false);
    }
  }

  async function loadCandidate(resumeIdentity: string) {
    const seq = loadSeq.current + 1;
    loadSeq.current = seq;
    setLoading(true);
    setError("");
    setCandidate(null);
    setProjects(null);
    setResumeDocument(null);
    setSummary(null);
    try {
      const [detail, projectPayload, documentPayload] = await Promise.all([
        getCandidateDetail(resumeIdentity),
        getCandidateProjects(resumeIdentity),
        getCandidateResumeDocument(resumeIdentity),
      ]);
      if (loadSeq.current !== seq) return;
      setCandidate(detail);
      setProjects(projectPayload);
      setResumeDocument(documentPayload);
    } catch (err) {
      if (loadSeq.current !== seq) return;
      reportError(err);
    } finally {
      if (loadSeq.current !== seq) return;
      setLoading(false);
    }
  }

  async function handleGenerateSummary() {
    if (!selectedIdentity) return;
    setSummaryLoading(true);
    setError("");
    try {
      setSummary(await generateCandidateSummary(selectedIdentity));
    } catch (err) {
      reportError(err);
    } finally {
      setSummaryLoading(false);
    }
  }

  async function handleCheckLlm() {
    setLlmChecking(true);
    setError("");
    try {
      setLlmStatus(await getLlmStatus());
    } catch (err) {
      reportError(err);
    } finally {
      setLlmChecking(false);
    }
  }

  async function handleIngestResumes() {
    if (ingestingRef.current) {
      setIngestMessage("已有导入任务正在运行，请等待当前任务完成。");
      return;
    }
    ingestingRef.current = true;
    setIngesting(true);
    setIngestionFeedbackHidden(false);
    setError("");
    setIngestMessage("");
    setIngestDetails([]);
    setIngestStatus({
      running: true,
      phase: "starting",
      mode: "directory",
      directory: "resume",
      uploaded_file: "",
      total_files: 0,
      current_index: 0,
      current_file: "",
      current_step: "正在提交重建入库任务",
      success_count: 0,
      error_count: 0,
      message: "正在提交任务：先清空旧数据库和向量库，再遍历 data/resume 批量入库...",
      recent_messages: ["正在提交任务：先清空旧数据库和向量库，再遍历 data/resume 批量入库..."],
    });
    startIngestionPolling();
    try {
      const previousIdentity = selectedIdentity;
      const result = await ingestResumeFiles("resume", true);
      await completeIngestionResult(result, previousIdentity);
    } catch (err) {
      reportError(err);
    } finally {
      await refreshIngestionStatus();
      stopIngestionPolling();
      ingestingRef.current = false;
      setIngesting(false);
    }
  }

  async function handleClearCandidates() {
    if (ingestingRef.current) {
      setIngestMessage("已有导入或清空任务正在运行，请等待当前任务完成。");
      return;
    }
    ingestingRef.current = true;
    setIngesting(true);
    setIngestionFeedbackHidden(false);
    setError("");
    setIngestMessage("");
    setIngestDetails([]);
    setIngestStatus({
      running: true,
      phase: "running",
      mode: "clear",
      directory: "data/resume",
      uploaded_file: "",
      total_files: 0,
      current_index: 0,
      current_file: "",
      current_step: "清空候选人库",
      success_count: 0,
      error_count: 0,
      message: "正在清空候选人库...",
      recent_messages: ["正在清空候选人库..."],
    });
    startIngestionPolling();
    try {
      const result = await clearResumeData();
      applyIngestionResultMessage(result, selectedIdentity);
      setCandidates([]);
      setSelectedIdentity("");
      setCandidate(null);
      setProjects(null);
      setResumeDocument(null);
      setSummary(null);
      await loadCandidates();
    } catch (err) {
      reportError(err);
    } finally {
      await refreshIngestionStatus();
      stopIngestionPolling();
      ingestingRef.current = false;
      setIngesting(false);
    }
  }

  async function handleUploadResume(file: File) {
    if (ingestingRef.current) {
      setIngestMessage("已有导入任务正在运行，请等待当前任务完成。");
      return;
    }
    ingestingRef.current = true;
    setIngesting(true);
    setIngestionFeedbackHidden(false);
    setError("");
    setIngestMessage("");
    setIngestDetails([]);
    setIngestStatus({
      running: true,
      phase: "starting",
      mode: "upload",
      directory: "resume/uploads",
      uploaded_file: file.name,
      total_files: 1,
      current_index: 0,
      current_file: file.name,
      current_step: "正在上传简历",
      success_count: 0,
      error_count: 0,
      message: `正在上传：${file.name}`,
      recent_messages: [`正在上传：${file.name}`],
    });
    startIngestionPolling();
    try {
      const previousIdentity = selectedIdentity;
      const result = await uploadResumeFile(file);
      applyIngestionResultMessage(result, previousIdentity);
      finishUploadProgress(result);
      stopIngestionPolling();
      ingestingRef.current = false;
      setIngesting(false);
      if (hasIngestionSuccess(result)) {
        void refreshCandidatesAfterIngestion(result, previousIdentity);
      }
    } catch (err) {
      reportError(err);
      finishUploadProgress(null);
      stopIngestionPolling();
      ingestingRef.current = false;
      setIngesting(false);
    } finally {
      if (ingestingRef.current) {
        await refreshIngestionStatus();
        stopIngestionPolling();
        ingestingRef.current = false;
        setIngesting(false);
      }
    }
  }

  async function completeIngestionResult(result: IngestionResponse, previousIdentity: string) {
    applyIngestionResultMessage(result, previousIdentity);
    await refreshCandidatesAfterIngestion(result, previousIdentity);
  }

  function applyIngestionResultMessage(result: IngestionResponse, previousIdentity: string) {
    const okResults = result.results.filter((item) => item.status === "ok");
    const okIdentities = okResults.map((item) => item.resume_identity || "").filter(Boolean);
    const hasSuccess = hasIngestionSuccess(result);
    const hasFailure = hasIngestionFailure(result);
    const firstError = result.results.find((item) => item.status === "error")?.error || "";
    const resetWasApplied = Boolean(result.reset_summary?.enabled);
    const preferredIdentity = okIdentities.includes(previousIdentity) ? previousIdentity : okIdentities[0] || (resetWasApplied ? "" : previousIdentity);
    setIngestMessage(
      [
        result.message || `收集完成：${result.success_count}/${result.total_files} 成功，${result.error_count} 失败。`,
        result.uploaded_file && hasFailure && !hasSuccess ? `上传文件已保存，但入库失败${firstError ? `：${firstError}` : "。"}` : "",
        result.uploaded_file && hasSuccess ? "上传文件已持久保存，候选人源文件预览可继续使用。" : "",
        result.uploaded_file && hasSuccess ? "可点击“刷新候选人”确认列表更新。" : "",
        hasSuccess && preferredIdentity && preferredIdentity !== previousIdentity ? "已自动切换到本次新写入的候选人。" : "",
        hasSuccess && preferredIdentity && preferredIdentity === previousIdentity ? "已重新刷新当前候选人详情。" : "",
        hasSuccess && okIdentities.length ? "已入库，可在 AI 问答中使用。" : "",
      ]
        .filter(Boolean)
        .join(" ")
    );
    setIngestDetails(buildIngestDetails(result));
  }

  async function refreshCandidatesAfterIngestion(result: IngestionResponse, previousIdentity: string) {
    const okResults = result.results.filter((item) => item.status === "ok");
    const okIdentities = okResults.map((item) => item.resume_identity || "").filter(Boolean);
    const resetWasApplied = Boolean(result.reset_summary?.enabled);
    const preferredIdentity = okIdentities.includes(previousIdentity) ? previousIdentity : okIdentities[0] || (resetWasApplied ? "" : previousIdentity);
    await loadCandidates();
    if (preferredIdentity) {
      if (preferredIdentity === previousIdentity) {
        await loadCandidate(preferredIdentity);
      } else {
        setSelectedIdentity(preferredIdentity);
      }
    } else if (resetWasApplied) {
      setSelectedIdentity("");
      setCandidate(null);
      setProjects(null);
      setResumeDocument(null);
      setSummary(null);
    }
  }

  async function handleRefreshCandidates() {
    setRefreshingCandidates(true);
    setError("");
    try {
      await loadCandidates();
      if (selectedIdentity) {
        await loadCandidate(selectedIdentity);
      }
    } catch (err) {
      reportError(err);
    } finally {
      setRefreshingCandidates(false);
    }
  }

  function finishUploadProgress(result: IngestionResponse | null) {
    setIngestStatus((status) => ({
      ...(status || {
        running: false,
        phase: "done",
        mode: "upload",
        directory: "resume/uploads",
        uploaded_file: "",
        total_files: 1,
        current_index: 1,
        current_file: "",
        current_step: "",
        success_count: 0,
        error_count: 0,
        message: "",
        recent_messages: [],
      }),
      running: false,
      phase: "done",
      current_step: result?.error_count ? "上传入库失败" : "上传入库完成",
      success_count: result?.success_count ?? status?.success_count ?? 0,
      error_count: result?.error_count ?? status?.error_count ?? 0,
      message: result?.message || status?.message || "",
    }));
  }

  function startIngestionPolling() {
    stopIngestionPolling();
    void refreshIngestionStatus();
    ingestPollRef.current = setInterval(() => {
      void refreshIngestionStatus();
    }, 900);
  }

  function stopIngestionPolling() {
    if (!ingestPollRef.current) return;
    clearInterval(ingestPollRef.current);
    ingestPollRef.current = null;
  }

  async function refreshIngestionStatus() {
    try {
      const nextStatus = await getIngestionStatus();
      setIngestStatus((currentStatus) => {
        if (
          ingestingRef.current &&
          currentStatus?.mode === "upload" &&
          currentStatus.phase !== "done" &&
          (!nextStatus.running || nextStatus.mode !== "upload")
        ) {
          return currentStatus;
        }
        return nextStatus;
      });
    } catch {
      // Progress is best-effort; the final POST result still reports success/failure.
    }
  }

  async function handleAskQa(questionOverride?: string) {
    const question = (questionOverride || qaQuestion).trim();
    if (!question || qaLoading) return;
    setQaLoading(true);
    setQaError("");
    setQaQuestion("");
    const userMessage: QAChatMessage = {
      id: `user-${Date.now()}`,
      role: "user",
      text: question,
    };
    setQaMessages((items) => [...items, userMessage]);
    try {
      const response = await askResumeQa({
        question,
        session_context: qaSessionContext,
        use_llm: qaUseLlm,
        debug: qaDebug,
      });
      setQaSessionContext(response.updated_session_context || {});
      setQaMessages((items) => [
        ...items,
        {
          id: `assistant-${Date.now()}`,
          role: "assistant",
          text: response.answer || response.clarification_question || "当前没有生成答案。",
          response,
        },
      ]);
    } catch (err) {
      reportError(err, setQaError);
    } finally {
      setQaLoading(false);
    }
  }

  function handleQaSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void handleAskQa();
  }

  function handleQaOption(option: string) {
    const latestAssistant = [...qaMessages].reverse().find((item) => item.response)?.response;
    const latestUser = [...qaMessages].reverse().find((item) => item.role === "user");
    const followUpQuestion = latestAssistant?.clarification_required && latestUser
      ? `${latestUser.text} ${option}`
      : option;
    void handleAskQa(followUpQuestion);
  }

  function handleResetQa() {
    setQaQuestion("");
    setQaMessages([]);
    setQaSessionContext({});
    setQaError("");
  }

  async function handleUnlock(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const token = passwordInput.trim();
    if (!token) {
      setError("请输入访问密码。");
      return;
    }
    setAuthChecking(true);
    setError("");
    setAccessToken(token);
    try {
      const payload = await getCandidates();
      setCandidates(payload.candidates || []);
      setAuthRequired(false);
      setAccessTokenPresent(true);
      setPasswordInput("");
      void handleCheckLlm();
    } catch (err) {
      clearAccessToken();
      setAccessTokenPresent(false);
      setAuthRequired(true);
      setError(normalizeError(err));
    } finally {
      setAuthChecking(false);
    }
  }

  function handleLock() {
    clearAccessToken();
    setAccessTokenPresent(false);
    setAuthRequired(true);
    setPasswordInput("");
    setCandidates([]);
    setSelectedIdentity("");
    setCandidate(null);
    setProjects(null);
    setResumeDocument(null);
    setSummary(null);
    setQaMessages([]);
    setQaSessionContext({});
    setError("");
  }

  return (
    <div className="flex min-h-screen bg-slate-100 text-slate-900">
      <aside className="flex w-64 shrink-0 flex-col border-r border-slate-200 bg-white">
        <div className="border-b border-slate-200 px-5 py-5">
          <div className="flex items-center gap-2 text-lg font-semibold">
            <FileSearch className="h-5 w-5 text-emerald-600" />
            简历候选人库
          </div>
          <div className="mt-1 text-sm text-slate-500">候选人信息展示</div>
        </div>

        <nav className="border-b border-slate-200 p-3">
          <NavButton icon={<UserRound className="h-4 w-4" />} label="候选人信息" active={activeView === "candidates"} onClick={() => setActiveView("candidates")} />
          <NavButton icon={<MessageSquareText className="h-4 w-4" />} label="AI 问答" active={activeView === "qa"} onClick={() => setActiveView("qa")} />
        </nav>
        <div className="mt-auto border-t border-slate-200 p-4 text-xs leading-6 text-slate-500">
          {activeView === "qa" ? "AI 问答支持页面内多轮追问，并展示排序、证据和调试链路。" : "候选人搜索、下拉选择、个人信息、工作经历、项目和总结都在右侧页面完成。"}
        </div>
      </aside>

      <main className="min-w-0 flex-1 p-6">
        <div className="mx-auto max-w-[1680px] space-y-5">
          <header className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <h1 className="text-2xl font-semibold tracking-tight">{activeView === "qa" ? "AI 问答" : "候选人信息"}</h1>
              <p className="mt-1 text-sm text-slate-500">
                {activeView === "qa" ? "在右侧进行招聘问答，并查看排序、评分、证据和追问状态。" : "筛选候选人后，在同一页查看档案、经历、项目和总结。"}
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              {accessTokenPresent ? (
                <Button onClick={handleLock} variant="outline">
                  <LogOut className="mr-2 h-4 w-4" />
                  锁定
                </Button>
              ) : null}
              <Button onClick={handleCheckLlm} disabled={llmChecking}>
                {llmChecking ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <MonitorCheck className="mr-2 h-4 w-4" />}
                检查总结服务
              </Button>
            </div>
          </header>

          {authRequired ? (
            <AccessPasswordPanel
              value={passwordInput}
              checking={authChecking}
              onChange={setPasswordInput}
              onSubmit={handleUnlock}
            />
          ) : null}
          {error ? <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div> : null}
          {llmStatus ? <LlmStatusPanel status={llmStatus} onClose={() => setLlmStatus(null)} /> : null}
          {activeView === "candidates" ? (
            <>
              {loading ? <LoadingRow text="正在读取候选人数据" /> : null}

              <ResumeIngestionPanel
                ingesting={ingesting}
                refreshingCandidates={refreshingCandidates}
                message={ingestMessage}
                details={ingestDetails}
                status={ingestStatus}
                feedbackHidden={ingestionFeedbackHidden}
                onUploadClick={() => uploadInputRef.current?.click()}
                onScan={handleIngestResumes}
                onClear={handleClearCandidates}
                onRefreshCandidates={handleRefreshCandidates}
                onHideFeedback={() => setIngestionFeedbackHidden(true)}
              />
              <input
                ref={uploadInputRef}
                type="file"
                accept=".pdf,.doc,.docx"
                className="hidden"
                onChange={(event) => {
                  const file = event.currentTarget.files?.[0];
                  event.currentTarget.value = "";
                  if (file) void handleUploadResume(file);
                }}
              />

              <CandidateBrowser
                allCandidates={candidates}
                keyword={keyword}
                selectedIdentity={selectedIdentity}
                onKeywordChange={setKeyword}
                onSelect={setSelectedIdentity}
              />

              {selectedIdentity ? (
                <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_400px] 2xl:grid-cols-[minmax(0,1fr)_420px] xl:items-start">
                  <div className="min-w-0 space-y-5">
                    <ProfileView candidate={candidate} />
                    <ProjectsView projects={projects} />
                    <SummaryView
                      candidate={candidate}
                      summary={summary}
                      loading={summaryLoading}
                      onGenerate={handleGenerateSummary}
                    />
                  </div>
                  <OriginalResumePanel document={resumeDocument} loading={loading && Boolean(selectedIdentity)} />
                </div>
              ) : (
                <CandidateSelectionEmptyState hasCandidates={candidates.length > 0} />
              )}
            </>
          ) : (
            <AIQAWorkspace
              question={qaQuestion}
              messages={qaMessages}
              loading={qaLoading}
              error={qaError}
              useLlm={qaUseLlm}
              debug={qaDebug}
              advancedDebug={qaAdvancedDebug}
              sessionContext={qaSessionContext}
              onQuestionChange={setQaQuestion}
              onSubmit={handleQaSubmit}
              onAskOption={handleQaOption}
              onUseLlmChange={setQaUseLlm}
              onDebugChange={setQaDebug}
              onAdvancedDebugChange={setQaAdvancedDebug}
              onReset={handleResetQa}
            />
          )}
        </div>
      </main>
    </div>
  );
}

function ResumeIngestionPanel({
  ingesting,
  refreshingCandidates,
  message,
  details,
  status,
  feedbackHidden,
  onUploadClick,
  onScan,
  onClear,
  onRefreshCandidates,
  onHideFeedback,
}: {
  ingesting: boolean;
  refreshingCandidates: boolean;
  message: string;
  details: string[];
  status: IngestionStatus | null;
  feedbackHidden: boolean;
  onUploadClick: () => void;
  onScan: () => void;
  onClear: () => void;
  onRefreshCandidates: () => void;
  onHideFeedback: () => void;
}) {
  const showProgress = Boolean(status?.running || (ingesting && status?.mode === "upload" && status.phase !== "done"));
  const showFeedback = !feedbackHidden && (Boolean(message) || showProgress);

  return (
    <Card className="border-emerald-200">
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <CardTitle className="flex items-center gap-2">
              <DatabaseZap className="h-5 w-5 text-emerald-600" />
              简历入库
            </CardTitle>
            <CardDescription className="mt-1">
              上传简历、扫描 data/resume 样例目录，或清空当前候选人库。
            </CardDescription>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button onClick={onUploadClick} disabled={ingesting} aria-busy={ingesting}>
              {ingesting && status?.mode === "upload" ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Upload className="mr-2 h-4 w-4" />}
              上传简历并入库
            </Button>
            <Button onClick={onScan} disabled={ingesting} aria-busy={ingesting} variant="outline">
              {ingesting && status?.mode === "directory" ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <DatabaseZap className="mr-2 h-4 w-4" />}
              清空旧数据并遍历 data/resume
            </Button>
            <Button onClick={onClear} disabled={ingesting || refreshingCandidates} aria-busy={ingesting && status?.mode === "clear"} variant="outline" className="border-rose-200 text-rose-700 hover:bg-rose-50">
              {ingesting && status?.mode === "clear" ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Trash2 className="mr-2 h-4 w-4" />}
              清空候选人库
            </Button>
            <Button onClick={onRefreshCandidates} disabled={ingesting || refreshingCandidates} variant="outline">
              {refreshingCandidates ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Search className="mr-2 h-4 w-4" />}
              刷新候选人
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid gap-3 md:grid-cols-3">
          <InfoCell label="上传存储" value="data/resume/uploads" />
          <InfoCell label="支持格式" value="PDF / DOC / DOCX" />
          <InfoCell label="批量扫描" value="先清空 SQLite/Chroma，再重建入库" />
        </div>
        {showFeedback ? (
          <div className="relative space-y-3">
            <button
              type="button"
              onClick={onHideFeedback}
              className="absolute right-2 top-2 z-10 rounded-full p-1 text-slate-400 transition hover:bg-white/80 hover:text-slate-700"
              aria-label="隐藏实时信息"
              title="隐藏实时信息"
            >
              <X className="h-4 w-4" />
            </button>
            {message ? (
              <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 pr-10 text-sm text-emerald-800">
                <div>{message}</div>
                {details.length ? (
                  <div className="mt-2 space-y-1 text-xs leading-5 text-emerald-700">
                    {details.map((item) => (
                      <div key={item}>{item}</div>
                    ))}
                  </div>
                ) : null}
              </div>
            ) : null}
            {showProgress ? <IngestionProgress status={status} /> : null}
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

function CandidateBrowser({
  allCandidates,
  keyword,
  selectedIdentity,
  onKeywordChange,
  onSelect,
}: {
  allCandidates: CandidateListItem[];
  keyword: string;
  selectedIdentity: string;
  onKeywordChange: (value: string) => void;
  onSelect: (value: string) => void;
}) {
  const optionCandidates = keyword.trim()
    ? allCandidates.filter((item) =>
        [item.name, item.job_intent, item.location_raw, item.resume_identity]
          .join(" ")
          .toLowerCase()
          .includes(keyword.trim().toLowerCase()),
      )
    : allCandidates;

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <CardTitle>候选人</CardTitle>
            <CardDescription>支持搜索，也可以用下拉列表直接定位候选人。</CardDescription>
          </div>
          <div className="grid w-full gap-3 lg:w-[620px] lg:grid-cols-2">
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-3 h-4 w-4 text-slate-400" />
              <Input value={keyword} onChange={(event) => onKeywordChange(event.target.value)} placeholder="搜索候选人" className="pl-9" />
            </div>
            <select
              value={selectedIdentity}
              onChange={(event) => onSelect(event.target.value)}
              disabled={!optionCandidates.length}
              className="h-10 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 outline-none focus:border-slate-400"
            >
              <option value="">请选择候选人</option>
              {optionCandidates.map((item) => (
                <option key={item.resume_identity} value={item.resume_identity}>
                  {item.name || "未命名候选人"}{item.job_intent ? ` - ${item.job_intent}` : ""}
                </option>
              ))}
            </select>
          </div>
        </div>
      </CardHeader>
    </Card>
  );
}

function CandidateSelectionEmptyState({ hasCandidates }: { hasCandidates: boolean }) {
  return (
    <Card className="border-dashed">
      <CardHeader>
        <CardTitle>请选择一个候选人查看详情</CardTitle>
        <CardDescription>
          {hasCandidates ? "从上方下拉框选择候选人后，会展示个人信息、项目经历、总结和原简历。" : "当前还没有候选人数据，也可以先在上方上传一份简历并入库。"}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-4 text-sm leading-6 text-slate-600">
          也可以先在上方上传一份简历并入库，系统会自动切换到新写入的候选人。
        </div>
      </CardContent>
    </Card>
  );
}

function ProfileView({ candidate }: { candidate: CandidateDetail | null }) {
  if (!candidate) return <EmptyState title="暂无候选人" text="候选人加载后会显示个人信息和教育经历。" />;
  return (
    <div className="space-y-5">
      <WorkProfileStrip candidate={candidate} />

      <div className="grid gap-5 2xl:grid-cols-[minmax(360px,0.9fr)_minmax(300px,0.72fr)_minmax(360px,0.86fr)]">
        <Card>
          <CardHeader>
            <CardTitle>个人信息</CardTitle>
            {candidate.file_name ? <CardDescription>{candidate.file_name}</CardDescription> : null}
          </CardHeader>
          <CardContent>
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-2">
              <InfoCell label="姓名" value={candidate.name.value} />
              <InfoCell label="求职意向" value={candidate.job_intent.value} />
              <InfoCell label="所在地" value={candidate.location_raw.value} />
              <InfoCell label="电话" value={candidate.contact.phone?.value} />
              <InfoCell label="邮箱" value={candidate.contact.email?.value} />
              <InfoCell label="微信" value={candidate.contact.wechat?.value} />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>教育经历</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {candidate.education_experiences.map((item) => (
              <EducationRow key={`${item.school_name}-${item.major}-${item.start_date}`} item={item} />
            ))}
            {!candidate.education_experiences.length ? <MutedText text="暂无教育经历。" /> : null}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>能力标签</CardTitle>
            <CardDescription>技能、经验和领域聚合。</CardDescription>
          </CardHeader>
          <CardContent>
            <SkillSections candidate={candidate} />
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function WorkProfileStrip({ candidate }: { candidate: CandidateDetail }) {
  const profile = normalizeWorkProfile(candidate);
  return (
    <Card className="border-slate-300">
      <CardContent className="p-4">
        <div className="grid gap-4 xl:grid-cols-[220px_minmax(0,1fr)_minmax(0,1fr)]">
          <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-3">
            <div className="text-xs font-semibold text-slate-500">工作画像</div>
            <div className="mt-2 flex flex-wrap items-baseline gap-2">
              <span className="text-2xl font-semibold text-slate-950">{profile.years_label}</span>
              <span className="text-xs text-slate-500">可信度 {profile.confidence_label || "待复核"}</span>
            </div>
          </div>
          <CompactTagList title="主要领域" values={profile.domains} fallback="领域待补充" limit={5} />
          <CompactTagList title="角色 / 公司" values={[...profile.roles.slice(0, 3), ...profile.companies.slice(0, 3)]} fallback="角色待补充" limit={6} />
        </div>
      </CardContent>
    </Card>
  );
}

function ProjectsView({ projects }: { projects: ClassifiedProjects | null }) {
  if (!projects) return <EmptyState title="暂无项目信息" text="选择候选人后会显示普通项目和工作经历。" />;
  const allProjects = mergeProjects(projects.ordinary_projects, projects.work_embedded_projects);
  return (
    <div className="space-y-5">
      <Card>
        <CardHeader>
          <CardTitle>工作经历</CardTitle>
          <CardDescription>按时间和公司展示候选人的工作记录。</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {projects.work_experiences.map((item) => (
            <WorkRow key={`${item.work_ref}-${item.company_name}`} item={item} />
          ))}
          {!projects.work_experiences.length ? <MutedText text="暂无工作经历。" /> : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>项目信息</CardTitle>
          <CardDescription>统一展示普通项目和从工作经历中识别出的项目。</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <SectionLabel title="项目" count={allProjects.length} />
          {allProjects.map((item) => (
            <ProjectRow key={`${item.project_id}-${item.project_name_raw}`} project={item} evidence={projectDisplayEvidence(item, projects.evidence_chunks)} />
          ))}
          {!allProjects.length ? <MutedText text="暂无项目信息。" /> : null}
        </CardContent>
      </Card>
    </div>
  );
}

function SummaryView({
  candidate,
  summary,
  loading,
  onGenerate,
}: {
  candidate: CandidateDetail | null;
  summary: SummaryResponse | null;
  loading: boolean;
  onGenerate: () => void;
}) {
  const sections = summary?.summary_sections;
  return (
    <div className="space-y-5">
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <CardTitle>总结检索</CardTitle>
              <CardDescription>后端聚合个人信息、普通项目、工作经历，再返回总览与分段总结。</CardDescription>
            </div>
            <Button onClick={onGenerate} disabled={!candidate || loading}>
              {loading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Sparkles className="mr-2 h-4 w-4" />}
              生成总结
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {summary ? (
            <div className="space-y-3">
              <div className="rounded-lg border border-slate-200 bg-slate-50 p-4 text-sm leading-7 text-slate-800">
                {summary.summary || sections?.overall_summary}
              </div>
              {summary.llm_error ? <div className="text-sm text-amber-700">总结服务暂不可用，已展示基础摘要。</div> : null}
            </div>
          ) : (
            <MutedText text="点击生成后会显示后端返回的 summary 和 summary_sections。" />
          )}
        </CardContent>
      </Card>

      {sections ? (
        <div className="grid gap-5 xl:grid-cols-3">
          <SummaryCard title="个人总结" text={sections.personal_summary} />
          <SummaryCard title="项目总结" text={sections.project_summary} />
          <SummaryCard title="工作经历总结" text={sections.work_experience_summary} />
          <Card className="xl:col-span-3">
            <CardHeader>
              <CardTitle>亮点与风险</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-5 md:grid-cols-2">
              <ListBlock title="优势" items={sections.strengths} />
              <ListBlock title="需复核" items={sections.risks_or_missing_info} />
            </CardContent>
          </Card>
        </div>
      ) : null}
    </div>
  );
}

function OriginalResumePanel({ document, loading }: { document: ResumeDocument | null; loading: boolean }) {
  const previewUrl = document?.preview_url ? toApiUrl(document.preview_url) : "";
  const downloadUrl = document?.download_url ? toApiUrl(document.download_url) : "";
  const previewTitle = document?.file_name ? `原简历：${document.file_name}` : "原简历";

  return (
    <Card className="xl:sticky xl:top-6">
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <CardTitle className="flex items-center gap-2">
              <FileText className="h-4 w-4 text-emerald-600" />
              原简历
            </CardTitle>
            <CardDescription className="mt-1 truncate">
              {document?.file_name || "选择候选人后显示源文件"}
            </CardDescription>
          </div>
          {document?.extension ? <Badge className="shrink-0 uppercase">{document.extension.replace(".", "")}</Badge> : null}
        </div>
        {downloadUrl ? (
          <div className="flex flex-wrap gap-2 pt-1">
            <a
              href={previewUrl || downloadUrl}
              target="_blank"
              rel="noreferrer"
              className="inline-flex h-9 items-center justify-center rounded-lg border border-slate-200 bg-white px-3 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-50"
            >
              <ExternalLink className="mr-2 h-4 w-4" />
              打开
            </a>
            <a
              href={downloadUrl}
              className="inline-flex h-9 items-center justify-center rounded-lg border border-slate-200 bg-white px-3 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-50"
            >
              <Download className="mr-2 h-4 w-4" />
              下载
            </a>
          </div>
        ) : null}
      </CardHeader>
      <CardContent>
        {loading ? (
          <div className="flex h-[520px] items-center justify-center rounded-lg border border-slate-200 bg-slate-50 text-sm text-slate-500 xl:h-[calc(100vh-260px)] xl:min-h-[560px]">
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            正在读取原简历
          </div>
        ) : document?.source_available && previewUrl ? (
          <div className="h-[560px] overflow-hidden rounded-lg border border-slate-200 bg-white xl:h-[calc(100vh-260px)] xl:min-h-[620px]">
            <iframe
              key={`${document.resume_identity}-${document.preview_url}`}
              title={previewTitle}
              src={previewUrl}
              className="h-full w-full bg-white"
            />
          </div>
        ) : (
          <div className="flex h-[360px] flex-col items-center justify-center rounded-lg border border-dashed border-slate-200 bg-slate-50 px-6 text-center">
            <FileText className="h-8 w-8 text-slate-400" />
            <div className="mt-3 text-sm font-medium text-slate-700">暂无可预览的源文件</div>
            <div className="mt-2 max-w-[320px] text-sm leading-6 text-slate-500">
              {document?.file_name ? "该文件不存在或格式暂不支持预览。" : "当前候选人未关联原始简历文件。"}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function AIQAWorkspace({
  question,
  messages,
  loading,
  error,
  useLlm,
  debug,
  advancedDebug,
  sessionContext,
  onQuestionChange,
  onSubmit,
  onAskOption,
  onUseLlmChange,
  onDebugChange,
  onAdvancedDebugChange,
  onReset,
}: {
  question: string;
  messages: QAChatMessage[];
  loading: boolean;
  error: string;
  useLlm: boolean;
  debug: boolean;
  advancedDebug: boolean;
  sessionContext: Record<string, unknown>;
  onQuestionChange: (value: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onAskOption: (value: string) => void;
  onUseLlmChange: (value: boolean) => void;
  onDebugChange: (value: boolean) => void;
  onAdvancedDebugChange: (value: boolean) => void;
  onReset: () => void;
}) {
  const latestResponse = [...messages].reverse().find((item) => item.response)?.response;
  const hasContext = Object.keys(sessionContext).length > 0;
  return (
    <div className={debug ? "mx-auto grid w-full max-w-[1280px] gap-5" : "grid gap-5 xl:grid-cols-[minmax(0,1fr)_420px]"}>
      <div className="space-y-5">
        <Card>
          <CardHeader>
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <CardTitle>问答输入</CardTitle>
                <CardDescription>支持候选人数量、筛选、介绍、比较、排序和证据追问。</CardDescription>
              </div>
              <div className="flex flex-wrap gap-2">
                <label className="flex h-10 items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-700">
                  <input checked={useLlm} onChange={(event) => onUseLlmChange(event.target.checked)} type="checkbox" />
                  LLM
                </label>
                <label className="flex h-10 items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-700">
                  <input checked={debug} onChange={(event) => onDebugChange(event.target.checked)} type="checkbox" />
                  Debug
                </label>
                {debug ? (
                  <label className="flex h-10 items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-700">
                    <input checked={advancedDebug} onChange={(event) => onAdvancedDebugChange(event.target.checked)} type="checkbox" />
                    显示高级调试信息
                  </label>
                ) : null}
                <Button onClick={onReset} variant="outline" disabled={loading && !messages.length}>
                  重置会话
                </Button>
              </div>
            </div>
          </CardHeader>
          <CardContent>
            <form onSubmit={onSubmit} className="flex flex-col gap-3 sm:flex-row">
              <Input
                value={question}
                onChange={(event) => onQuestionChange(event.target.value)}
                placeholder="例如：有多少候选人，按综合匹配度排名？"
                disabled={loading}
              />
              <Button type="submit" disabled={loading || !question.trim()} className="shrink-0">
                {loading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Send className="mr-2 h-4 w-4" />}
                发送
              </Button>
            </form>
            <div className="mt-3 flex flex-wrap gap-2">
              {["有多少候选人，按综合匹配度排名？", "金融方向候选人有多少，都有谁？", "运营方向候选人有哪些项目经验？"].map((sample) => (
                <button
                  key={sample}
                  type="button"
                  onClick={() => onAskOption(sample)}
                  disabled={loading}
                  className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600 hover:bg-white disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {sample}
                </button>
              ))}
            </div>
          </CardContent>
        </Card>

        {error ? <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div> : null}

        <Card>
          <CardHeader>
            <CardTitle>问答历史</CardTitle>
            <CardDescription>{hasContext ? "当前会话已有上下文，可继续问“他/第一名/这两个人”。" : "当前是新的页面内会话。"}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {messages.length ? (
              messages.map((message) => <QAChatBubble key={message.id} message={message} onAskOption={onAskOption} loading={loading} />)
            ) : (
              <div className="rounded-lg border border-dashed border-slate-200 bg-slate-50 p-6 text-center text-sm text-slate-500">
                还没有问题。可以从上方输入，或点击示例问题开始。
              </div>
            )}
            {loading ? <LoadingRow text="AI 问答正在生成结果" /> : null}
          </CardContent>
        </Card>

        {debug ? (
          <div className="space-y-5">
            <QATracePanel response={latestResponse} advancedDebug={advancedDebug} />
          </div>
        ) : null}
      </div>

      <div className={debug ? "grid gap-5 lg:grid-cols-2" : "space-y-5"}>
        <QAStatusPanel response={latestResponse} sessionContext={sessionContext} debug={debug} />
        <QAContextPanel response={latestResponse} sessionContext={sessionContext} />
      </div>
    </div>
  );
}

function QAChatBubble({ message, onAskOption, loading }: { message: QAChatMessage; onAskOption: (value: string) => void; loading: boolean }) {
  const isUser = message.role === "user";
  const response = message.response;
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div className={`max-w-[860px] rounded-lg border px-4 py-3 text-sm leading-7 ${isUser ? "border-slate-900 bg-slate-900 text-white" : "border-slate-200 bg-white text-slate-800"}`}>
        <div className="flex items-center gap-2 text-xs font-semibold opacity-80">
          {isUser ? <UserRound className="h-3.5 w-3.5" /> : <Bot className="h-3.5 w-3.5" />}
          {isUser ? "你" : response?.status === "needs_clarification" ? "需要追问" : "AI 问答"}
        </div>
        <div className="mt-2 whitespace-pre-wrap">{message.text}</div>
        {response?.clarification_required && response.clarification_options.length ? (
          <div className="mt-3 flex flex-wrap gap-2">
            {response.clarification_options.map((option) => (
              <button
                key={option}
                type="button"
                onClick={() => onAskOption(option)}
                disabled={loading}
                className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-1.5 text-xs text-amber-800 hover:bg-white disabled:cursor-not-allowed disabled:opacity-60"
              >
                {option}
              </button>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}

function QAStatusPanel({ response, sessionContext, debug }: { response?: QAAskResponse; sessionContext: Record<string, unknown>; debug: boolean }) {
  const status = response?.status || "idle";
  const diagnosis = response?.trace?.diagnosis;
  const statusLabel = status === "ok" ? "已完成" : status === "needs_clarification" ? "等待澄清" : status === "failed" ? "失败" : "未开始";
  const statusClass =
    status === "ok"
      ? "border-emerald-200 bg-emerald-50 text-emerald-800"
      : status === "needs_clarification"
        ? "border-amber-200 bg-amber-50 text-amber-800"
        : status === "failed"
          ? "border-red-200 bg-red-50 text-red-800"
          : "border-slate-200 bg-white text-slate-700";
  return (
    <Card>
      <CardHeader>
        <CardTitle>问答状态</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className={`rounded-lg border px-3 py-2 text-sm font-medium ${statusClass}`}>{statusLabel}</div>
        {debug && diagnosis?.headline ? (
          <div className={`rounded-lg border px-3 py-3 text-sm leading-6 ${diagnosisClass(diagnosis.level)}`}>
            <div className="flex items-start gap-2">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <div>
                <div className="font-medium">{diagnosis.headline}</div>
                {diagnosis.failed_node || diagnosis.failed_reason ? (
                  <div className="mt-1 text-xs opacity-80">
                    {[diagnosis.failed_node ? `节点 ${diagnosis.failed_node}` : "", diagnosis.failed_reason].filter(Boolean).join(" · ")}
                  </div>
                ) : null}
              </div>
            </div>
          </div>
        ) : null}
        <InfoCell label="候选池" value={Array.isArray(sessionContext.last_candidate_pool_names) ? sessionContext.last_candidate_pool_names.join("、") : "暂无"} />
        <InfoCell label="最近意图" value={String(sessionContext.last_intent || "暂无")} />
      </CardContent>
    </Card>
  );
}

function QAContextPanel({ response, sessionContext }: { response?: QAAskResponse; sessionContext: Record<string, unknown> }) {
  const snapshot = response?.trace?.session_context_snapshot;
  const current = snapshot?.current || sessionContext;
  const poolNames = Array.isArray(current.last_candidate_pool_names) ? current.last_candidate_pool_names.join("、") : "";
  const rankingNames = Array.isArray(current.last_ranking_candidate_names) ? current.last_ranking_candidate_names.join("、") : "";
  const comparisonNames = Array.isArray(current.last_comparison_candidate_names) ? current.last_comparison_candidate_names.join("、") : "";
  return (
    <Card>
      <CardHeader>
        <CardTitle>上下文记忆</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <InfoCell label="上一轮问题" value={String(current.last_user_question || "暂无")} />
        <InfoCell label="上一轮意图" value={String(current.last_intent || "暂无")} />
        <InfoCell label="候选池" value={poolNames || "暂无"} />
        <InfoCell label="上一轮排序" value={rankingNames || "暂无"} />
        <InfoCell label="比较对象" value={comparisonNames || "暂无"} />
      </CardContent>
    </Card>
  );
}

function QAComparisonProfilePanel({ profiles }: { profiles: QAAskResponse["comparison_profiles"] }) {
  if (!profiles.length) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle>比较对象经历</CardTitle>
        <CardDescription>双人比较时展示双方工作经历和项目经历。</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {profiles.map((profile) => (
          <div key={profile.resume_identity} className="rounded-lg border border-slate-200 bg-white p-3">
            <div className="font-semibold text-slate-900">{profile.name || profile.resume_identity}</div>
            {profile.job_intent ? <div className="mt-1 text-xs text-slate-500">{profile.job_intent}</div> : null}
            <div className="mt-3">
              <div className="text-xs font-semibold text-slate-500">工作经历</div>
              <div className="mt-2 space-y-2">
                {profile.work_experiences.length ? (
                  profile.work_experiences.slice(0, 3).map((item, index) => (
                    <div key={`${profile.resume_identity}-work-${index}`} className="text-sm leading-6 text-slate-700">
                      {[item.company_name, item.job_title_raw, dateRange(item.start_date, item.end_date)].filter(Boolean).join(" · ") || item.raw_line || "工作经历"}
                    </div>
                  ))
                ) : (
                  <MutedText text="暂无工作经历。" />
                )}
              </div>
            </div>
            <div className="mt-3">
              <div className="text-xs font-semibold text-slate-500">项目经历</div>
              <div className="mt-2 space-y-2">
                {profile.projects.length ? (
                  profile.projects.slice(0, 3).map((item, index) => (
                    <div key={`${profile.resume_identity}-project-${item.project_id || index}`} className="text-sm leading-6 text-slate-700">
                      {[item.project_name_raw, item.organization_raw, item.date_range_raw].filter(Boolean).join(" · ") || "项目经历"}
                    </div>
                  ))
                ) : (
                  <MutedText text="暂无项目经历。" />
                )}
              </div>
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

function QAEvidencePanel({ response }: { response?: QAAskResponse }) {
  const evidenceRefs = selectKeyEvidenceRefs(response);
  const grouped = groupEvidenceRefs(evidenceRefs);
  return (
    <Card>
      <CardHeader>
        <CardTitle>本轮关键依据</CardTitle>
        <CardDescription>只展示 Query-AI 从 Chroma 检索到的 evidence。</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {evidenceRefs.length ? (
          Object.entries(grouped).map(([group, refs]) =>
            refs.length ? (
              <div key={group} className="space-y-2">
                <div className="text-xs font-semibold text-slate-500">{group}</div>
                {refs.map((ref, index) => (
                  <div key={ref.evidence_id || `${ref.resume_identity}-${index}`} className="rounded-lg border border-slate-200 bg-white p-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge>{ref.candidate_name || ref.resume_identity || "候选人"}</Badge>
                      <Badge className="border-emerald-200 bg-emerald-50 text-emerald-700">Chroma evidence</Badge>
                      <span className="text-sm font-medium text-slate-900">{ref.project_title || ref.project_id || sourceTypeLabel(ref.source_type)}</span>
                    </div>
                    <div className="mt-2 text-sm leading-6 text-slate-700">{ref.summary || summarizeEvidenceRef(ref)}</div>
                    <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                      <span>{sourceTypeLabel(ref.source_type)}</span>
                      <span>强度 {ref.strength || 0}</span>
                    </div>
                  </div>
                ))}
              </div>
            ) : null
          )
        ) : (
          <MutedText text="未检索到 Chroma evidence。" />
        )}
      </CardContent>
    </Card>
  );
}

function QATracePanel({ response, advancedDebug }: { response?: QAAskResponse; advancedDebug: boolean }) {
  const trace = response?.trace;
  const diagnosis = trace?.diagnosis;
  const errors = trace?.validation_errors
    ? [...(trace.validation_errors.plan || []), ...(trace.validation_errors.execution || []), ...(trace.validation_errors.answer || [])]
    : [];
  return (
    <Card>
      <CardHeader>
        <CardTitle>Trace 摘要</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {trace ? (
          <>
            <div className="grid max-w-3xl gap-2 text-xs text-slate-600 sm:grid-cols-2">
              <div>Intent：<span className="font-medium text-slate-900">{trace.intent || "-"}</span></div>
              <div>Status：<span className="font-medium text-slate-900">{trace.final_status || "-"}</span></div>
              <div>Trace ID：<span className="break-all font-mono text-slate-700">{trace.trace_id || "-"}</span></div>
              {trace.log_file_hint ? <div>后端日志：<span className="break-all font-mono text-slate-700">{trace.log_file_hint}</span></div> : null}
            </div>

            {diagnosis ? <QADiagnosisPanel diagnosis={diagnosis} /> : null}

            <TraceFlowPanel response={response} advancedDebug={advancedDebug} />

            {advancedDebug ? (
              <details className="rounded-lg border border-slate-200 bg-white p-3">
                <summary className="cursor-pointer text-xs font-semibold uppercase tracking-wide text-slate-500">查看原始计划</summary>
                <div className="mt-3 grid gap-4 xl:grid-cols-2">
                  <TraceJsonPanel title="Semantic Plan" value={trace.semantic_plan} maxHeightClass="max-h-[520px]" />
                  <TraceJsonPanel title="Compiled Plan" value={trace.compiled_plan} maxHeightClass="max-h-[520px]" />
                </div>
              </details>
            ) : null}

            <div className="space-y-2">
              <div>
                <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Tools</div>
                <div className="mt-1 text-xs leading-5 text-slate-500">
                  执行证据：用于确认工具是否运行成功、是否返回空 evidence、以及错误或 warning 来自哪个工具。
                </div>
              </div>
              {(trace.tools || []).length ? (
                (trace.tools || []).map((tool, index) => (
                  <div key={`${tool.name}-${index}`} className="rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-700">
                    <span className="font-medium text-slate-900">{tool.name}</span>
                    <span className={tool.status === "ok" ? "ml-2 text-emerald-700" : "ml-2 text-rose-700"}>{tool.status}</span>
                    {tool.error ? <div className="mt-1 text-rose-700">{tool.error}</div> : null}
                    {tool.warnings?.length ? <div className="mt-1 text-amber-700">{tool.warnings.join("；")}</div> : null}
                  </div>
                ))
              ) : (
                <MutedText text="本轮没有调用工具。" />
              )}
            </div>

            {errors.length ? (
              <div className="rounded-lg bg-rose-50 p-3 text-xs leading-5 text-rose-700">
                {errors.map((error) => <div key={error}>{error}</div>)}
              </div>
            ) : null}
          </>
        ) : (
          <MutedText text="开启 Debug 后，新回答会返回 trace 摘要。" />
        )}
      </CardContent>
    </Card>
  );
}

function QADiagnosisPanel({ diagnosis }: { diagnosis: NonNullable<NonNullable<QAAskResponse["trace"]>["diagnosis"]> }) {
  const validationEntries = Object.entries(diagnosis.validation_errors || {}).filter(([, values]) => Array.isArray(values) && values.length);
  const usefulWarnings = (diagnosis.warnings || []).filter((warning) => !isLayoutAuditWarning(warning));
  const compactRoute = [diagnosis.route_from || "", diagnosis.route_to || ""].filter(Boolean).join(" -> ");
  return (
    <div className={`rounded-lg border p-3 text-xs leading-5 ${diagnosisClass(diagnosis.level)}`}>
      <div className="flex items-start gap-2">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
        <div className="min-w-0 flex-1">
          <div className="font-semibold">诊断摘要</div>
          <div className="mt-1 text-sm font-medium">{diagnosis.headline || "暂无诊断信息"}</div>
          <div className="mt-2 grid gap-1 sm:grid-cols-3">
            {diagnosis.failed_node ? <div>位置：{diagnosis.failed_node}</div> : null}
            {compactRoute ? <div>路由：{compactRoute}</div> : null}
            {diagnosis.route_reason || diagnosis.failed_reason ? <div>原因：{diagnosis.route_reason || diagnosis.failed_reason}</div> : null}
          </div>
          {diagnosis.suggested_check ? <div><span className="font-semibold">建议检查：</span>{diagnosis.suggested_check}</div> : null}
          {diagnosis.tool_failures?.length ? (
            <div className="mt-2">
              <div className="font-semibold">工具失败</div>
              {diagnosis.tool_failures.map((item, index) => (
                <div key={`${item.tool}-${index}`}>{item.tool}: {item.error || "failed"}</div>
              ))}
            </div>
          ) : null}
          {validationEntries.length ? (
            <div className="mt-2">
              <div className="font-semibold">Validator Errors</div>
              {validationEntries.map(([layer, values]) => (
                <div key={layer}>{layer}: {(values || []).join("；")}</div>
              ))}
            </div>
          ) : null}
          {usefulWarnings.length ? (
            <div className="mt-2">
              <div className="font-semibold">Warnings</div>
              {usefulWarnings.map((warning) => <div key={warning}>{warning}</div>)}
            </div>
          ) : null}
          <details className="mt-2">
            <summary className="cursor-pointer font-semibold">查看原始诊断</summary>
            <div className="mt-2 space-y-1 opacity-85">
              {diagnosis.impact ? <div><span className="font-semibold">影响：</span>{diagnosis.impact}</div> : null}
              {diagnosis.handling ? <div><span className="font-semibold">系统处理：</span>{diagnosis.handling}</div> : null}
              {diagnosis.technical_code ? <div className="break-all font-mono text-[11px]">technical: {diagnosis.technical_code}</div> : null}
              {diagnosis.warnings?.length ? <div>warnings: {diagnosis.warnings.join("；")}</div> : null}
              {diagnosis.trace_lookup ? <div className="break-all font-mono text-[11px]">{diagnosis.trace_lookup}</div> : null}
            </div>
          </details>
        </div>
      </div>
    </div>
  );
}

type TraceStep = NonNullable<NonNullable<QAAskResponse["trace"]>["decision_steps"]>[number];
type TraceRouteEvent = NonNullable<NonNullable<QAAskResponse["trace"]>["route_events"]>[number];
type TraceNodeDetailData = NonNullable<NonNullable<QAAskResponse["trace"]>["node_details"]>[string];
type TraceNodeStatus = "ok" | "repair" | "failed" | "clarification" | "final";

function TraceFlowPanel({ response, advancedDebug }: { response?: QAAskResponse; advancedDebug: boolean }) {
  const trace = response?.trace;
  const steps = trace?.decision_steps || [];
  const routeEvents = trace?.route_events || [];
  const nodeDetails = trace?.node_details || {};
  const [selectedGraphNode, setSelectedGraphNode] = useState<string>("");
  const [nodeDetailCollapsed, setNodeDetailCollapsed] = useState(false);

  const nodeEvents = steps.map((step) => ({
    step,
    status: traceStepStatus(step, routeEvents),
    routes: routeEvents.filter((event) => event.route_from === step.node),
  }));
  const issueSummaries = nodeEvents.flatMap(({ step, status, routes }) => traceIssueSummaries(step, status, routes));
  const defaultNode = [...nodeEvents].reverse().find((item) => item.status !== "ok" && item.status !== "final")?.step.node || steps[steps.length - 1]?.node || "";
  const selectedNode = selectedGraphNode || defaultNode;
  const selected = nodeEvents.find((item) => item.step.node === selectedNode) || nodeEvents[nodeEvents.length - 1];
  const selectedDetail = selectedNode ? nodeDetails[selectedNode] : undefined;

  useEffect(() => {
    setSelectedGraphNode(defaultNode);
  }, [defaultNode]);

  useEffect(() => {
    setNodeDetailCollapsed(false);
  }, [selectedNode]);

  if (!steps.length) return null;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-xs font-semibold uppercase text-slate-500">
          <Route className="h-4 w-4" />
          链路排查
        </div>
        <span className="text-xs text-slate-500">{steps.length} 个节点</span>
      </div>
      {issueSummaries.length ? (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-800">
          <span className="font-semibold text-amber-900">异常摘要：</span>
          {issueSummaries.slice(0, 3).join("；")}
          {issueSummaries.length > 3 ? `；另 ${issueSummaries.length - 3} 项` : ""}
        </div>
      ) : (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-800">本轮无异常决策。</div>
      )}
      <div className="overflow-x-auto rounded-lg border border-slate-200 bg-slate-50 p-3">
        <div className="flex min-w-max gap-2">
          {nodeEvents.map(({ step, status }, index) => (
            <button
              key={`${step.node}-${index}`}
              type="button"
              onClick={() => setSelectedGraphNode(step.node || "")}
              className={`w-52 shrink-0 rounded-md border px-3 py-2 text-left text-xs transition ${graphNodeClass(status, selectedNode === step.node)}`}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-semibold text-slate-900">{step.node || "node"}</span>
                <span className="text-[10px] text-slate-500">#{step.step || index + 1}</span>
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-2 text-slate-500">
                <span>{step.engine || "-"}</span>
                <Badge className={traceStatusBadgeClass(status)}>{status}</Badge>
              </div>
              {step.summary ? <div className="mt-1 line-clamp-2 text-slate-600">{step.summary}</div> : null}
              {typeof step.duration_ms === "number" ? <div className="mt-1 text-slate-400">{step.duration_ms}ms</div> : null}
            </button>
          ))}
        </div>
      </div>
      {selected ? (
        <TraceNodeDetail
          step={selected.step}
          status={selected.status}
          routes={selected.routes}
          detail={selectedDetail}
          advancedDebug={advancedDebug}
          collapsed={nodeDetailCollapsed}
          onCollapsedChange={setNodeDetailCollapsed}
        />
      ) : null}
    </div>
  );
}

function TraceNodeDetail({
  step,
  status,
  routes,
  detail,
  advancedDebug,
  collapsed,
  onCollapsedChange,
}: {
  step: TraceStep;
  status: TraceNodeStatus;
  routes: TraceRouteEvent[];
  detail?: TraceNodeDetailData;
  advancedDebug: boolean;
  collapsed: boolean;
  onCollapsedChange: (value: boolean) => void;
}) {
  const isIssue = status !== "ok" && status !== "final";
  return (
    <div className={`rounded-lg border p-3 text-xs leading-5 ${isIssue ? "border-amber-200 bg-amber-50 text-amber-900" : "border-slate-200 bg-white text-slate-600"}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <Badge className={traceStatusBadgeClass(status)}>{status}</Badge>
          <span className="font-semibold text-slate-900">{detail?.title || step.node || "node"}</span>
          <span>engine: {step.engine || "-"}</span>
          {typeof step.duration_ms === "number" ? <span>{step.duration_ms}ms</span> : null}
        </div>
        <Button
          type="button"
          variant="outline"
          onClick={() => onCollapsedChange(!collapsed)}
          className="h-8 gap-1.5 rounded-md px-2.5 text-xs"
        >
          {collapsed ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronUp className="h-3.5 w-3.5" />}
          {collapsed ? "更多细节" : "隐藏细节"}
        </Button>
      </div>
      {detail?.summary ? <div className="mt-3 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm leading-6 text-slate-800">{detail.summary}</div> : null}
      {detail?.checks?.length ? <TraceCheckList checks={detail.checks} /> : null}
      {detail ? (
        <>
          <div className="mt-3 grid gap-3 lg:grid-cols-3">
            <TraceNodeDetailBlock title="输入" value={detail.input} />
            <TraceNodeDetailBlock title="决策" value={detail.decision} />
            <TraceNodeDetailBlock title="输出" value={detail.output} />
          </div>
          {!collapsed && isRecord(detail.advanced?.router_audit) ? (
            <div className="mt-3">
              <TraceRouterRuleLayers value={detail.advanced.router_audit} />
            </div>
          ) : null}
          {advancedDebug && !collapsed && detail.advanced && Object.keys(detail.advanced).length ? (
            <details className="mt-3 rounded-md border border-slate-200 bg-white/80 px-3 py-2">
              <summary className="cursor-pointer font-semibold text-slate-900">查看高级调试信息</summary>
              <pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap break-words rounded bg-slate-950 p-3 text-[11px] leading-5 text-slate-100">
                {formatPrettyJson(detail.advanced)}
              </pre>
            </details>
          ) : null}
          {!collapsed && detail.raw && Object.keys(detail.raw).length ? (
            <details className="mt-3 rounded-md border border-slate-200 bg-white/80 px-3 py-2">
              <summary className="cursor-pointer font-semibold text-slate-900">查看原始节点片段</summary>
              <pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap break-words rounded bg-slate-950 p-3 text-[11px] leading-5 text-slate-100">
                {formatPrettyJson(detail.raw)}
              </pre>
            </details>
          ) : null}
        </>
      ) : (
        <>
          {step.summary ? <div className="mt-2">summary: {step.summary}</div> : null}
          {step.error_category ? <div className="mt-1 text-rose-700">category: {step.error_category}</div> : null}
          {step.fallback_reason ? <div className="mt-1 text-amber-700">fallback: {step.fallback_reason}</div> : null}
          {step.repair_action ? <div className="mt-1 text-amber-700">repair: {step.repair_action} / {step.repair_reason || "-"}</div> : null}
          {step.errors?.length ? <div className="mt-1 text-rose-700">errors: {step.errors.join("；")}</div> : null}
          {step.warnings?.length ? <div className="mt-1 text-amber-700">warnings: {step.warnings.join("；")}</div> : null}
        </>
      )}
      {!collapsed && routes.length ? (
        <div className="mt-3 space-y-2">
          <div className="font-semibold text-slate-900">相关路由</div>
          {routes.map((event, index) => (
            <div key={`${event.route_from}-${event.route_to}-${index}`} className="rounded-md bg-white/70 px-3 py-2">
              <span className="font-medium text-slate-900">{event.route_from || "-"}</span>
              <span className="mx-2 text-slate-400">-&gt;</span>
              <span className="font-medium text-slate-900">{event.route_to || "-"}</span>
              {event.reason ? <span className="ml-2 text-amber-700">{event.reason}</span> : null}
              {typeof event.retry_count === "number" ? <span className="ml-2 text-slate-500">retry={event.retry_count}</span> : null}
              {event.errors?.length ? <div className="mt-1 text-rose-700">{event.errors.join("；")}</div> : null}
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function TraceNodeDetailBlock({ title, value }: { title: string; value?: Record<string, unknown> }) {
  const entries = Object.entries(value || {}).filter(([, item]) => item !== undefined && item !== null && item !== "" && !(Array.isArray(item) && !item.length));
  return (
    <div className="min-w-0 rounded-md border border-slate-200 bg-white/80 p-3">
      <div className="mb-2 text-xs font-semibold text-slate-900">{title}</div>
      {entries.length ? (
        <div className="space-y-2">
          {entries.map(([key, item]) => (
            <div key={key} className="min-w-0">
              <div className="font-medium text-slate-500">{traceFieldLabel(key)}</div>
              <div className="mt-0.5 min-w-0 text-slate-800">{formatTraceField(key, item)}</div>
            </div>
          ))}
        </div>
      ) : (
        <MutedText text="暂无。" />
      )}
    </div>
  );
}

function TraceCheckList({ checks }: { checks: NonNullable<TraceNodeDetailData["checks"]> }) {
  return (
    <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
      {checks.map((check) => (
        <div key={`${check.label}-${check.status}`} className={`rounded-md border px-3 py-2 ${check.status === "ok" ? "border-emerald-200 bg-emerald-50 text-emerald-800" : "border-rose-200 bg-rose-50 text-rose-800"}`}>
          <div className="flex items-center justify-between gap-2">
            <span className="font-semibold">{check.label}</span>
            <Badge className={check.status === "ok" ? "border-emerald-200 bg-white text-emerald-700" : "border-rose-200 bg-white text-rose-700"}>{check.status}</Badge>
          </div>
          {check.detail ? <div className="mt-1 text-[11px] leading-5 opacity-85">{check.detail}</div> : null}
        </div>
      ))}
    </div>
  );
}

function formatTraceField(key: string, value: unknown): ReactNode {
  if (key === "tool_calls" && Array.isArray(value)) return <TraceToolCallCards calls={value} />;
  if (key === "compiled_tool_calls" && Array.isArray(value)) return <TraceToolCallCards calls={value} />;
  if (key === "tool_results" && Array.isArray(value)) return <TraceToolResultCards results={value} />;
  if (key === "claims" && Array.isArray(value)) return <TraceClaimCards claims={value} />;
  if (key === "rule_layers" && isRecord(value)) return <TraceRouterRuleLayers value={value} />;
  if (key === "router_audit" && isRecord(value)) return <TraceRouterRuleLayers value={value} />;
  return formatTraceNodeValue(value);
}

function traceFieldLabel(key: string): string {
  const labels: Record<string, string> = {
    answer_preview: "答案预览",
    claim_count: "结构化事实总数",
    claims: "结构化事实",
    used_evidence_count: "使用证据数",
    tool_calls: "工具调用",
    compiled_tool_calls: "最终工具调用",
    tool_results: "工具结果",
    warnings: "警告",
    errors: "错误",
    rule_layers: "路由规则分层",
    router_audit: "Router 决策审计",
  };
  return labels[key] || key;
}

function TraceRouterRuleLayers({ value }: { value: Record<string, unknown> }) {
  const hardRules = Array.isArray(value.hard_rules_applied) ? value.hard_rules_applied : [];
  const softHints = Array.isArray(value.soft_hints) ? value.soft_hints : [];
  const diagnostics = Array.isArray(value.diagnostics) ? value.diagnostics : [];
  const fieldChanges = Array.isArray(value.field_changes) ? value.field_changes : [];
  return (
    <div className="space-y-2 rounded-md border border-slate-200 bg-white/80 p-3">
      <div>
        <div className="font-semibold text-slate-900">Router 决策审计</div>
        <div className="mt-1 text-[11px] leading-5 text-slate-500">
          硬覆盖 = 系统必须修正；软提示 = 只提示，不改 LLM 判断；诊断 = 提醒后续 compiler/validator 注意。
        </div>
      </div>
      <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2">
        <div className="grid gap-2 text-xs sm:grid-cols-2">
          <div><span className="font-semibold text-slate-700">草稿来源：</span>{formatInlineTraceValue(value.draft_source)}</div>
          <div><span className="font-semibold text-slate-700">LLM/规则草稿：</span>{formatInlineTraceValue(value.draft_intent)} / {formatInlineTraceValue(value.draft_scenario)}</div>
          <div><span className="font-semibold text-slate-700">最终结果：</span>{formatInlineTraceValue(value.final_intent)} / {formatInlineTraceValue(value.final_scenario)}</div>
          <div><span className="font-semibold text-slate-700">硬覆盖：</span>{value.hard_override_applied ? "是" : "否"}</div>
          <div><span className="font-semibold text-slate-700">保留 LLM/草稿判断：</span>{value.llm_decision_kept === false ? "否" : "是"}</div>
        </div>
        {isRecord(value.final_scenarios) && Object.keys(value.final_scenarios).length ? (
          <div className="mt-2 text-xs text-slate-600">scenario：{Object.entries(value.final_scenarios).map(([key, item]) => `${key}=${formatInlineTraceValue(item)}`).join("；")}</div>
        ) : null}
      </div>
      <TraceRuleList title="硬覆盖" items={hardRules.length ? hardRules : fieldChanges.filter((item) => isRecord(item) && item.source === "hard_rule")} empty="无硬覆盖。" />
      <TraceRuleList title="字段变化" items={fieldChanges} empty="无字段变化。" />
      <TraceRuleList title="未覆盖提示" items={softHints} empty="无软提示。" />
      <TraceRuleList title="诊断" items={diagnostics} empty="无诊断风险。" />
    </div>
  );
}

function TraceRuleList({ title, items, empty }: { title: string; items: unknown[]; empty: string }) {
  return (
    <div className="rounded-md border border-slate-200 bg-white/80 px-3 py-2">
      <div className="mb-1 font-semibold text-slate-900">{title}</div>
      {items.length ? (
        <div className="space-y-1">
          {items.map((item, index) => (
            <div key={index} className="rounded bg-slate-50 px-2 py-1 text-xs leading-5 text-slate-700">{formatTraceNodeValue(item)}</div>
          ))}
        </div>
      ) : (
        <MutedText text={empty} />
      )}
    </div>
  );
}

function TraceToolCallCards({ calls }: { calls: unknown[] }) {
  return (
    <div className="space-y-2">
      {calls.slice(0, 8).map((raw, index) => {
        const call = isRecord(raw) ? raw : {};
        return (
          <div key={`${String(call.name || "tool")}-${index}`} className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-semibold text-slate-900">{String(call.name || "tool")}</span>
              {call.output_key ? <Badge>{String(call.output_key)}</Badge> : null}
            </div>
            {call.purpose ? <div className="mt-1 text-slate-600">{String(call.purpose)}</div> : null}
            {Array.isArray(call.depends_on) && call.depends_on.length ? <div className="mt-1 text-slate-500">依赖：{call.depends_on.map(String).join("、")}</div> : null}
            {isRecord(call.arguments) && Object.keys(call.arguments).length ? (
              <div className="mt-2 space-y-1">
                {Object.entries(call.arguments).slice(0, 6).map(([argKey, argValue]) => (
                  <div key={argKey} className="grid grid-cols-[112px_minmax(0,1fr)] gap-2 rounded bg-white px-2 py-1">
                    <span className="truncate text-slate-500">{argKey}</span>
                    <span className="break-words text-slate-800">{formatInlineTraceValue(argValue)}</span>
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        );
      })}
      {calls.length > 8 ? <div className="text-slate-400">+{calls.length - 8}</div> : null}
    </div>
  );
}

function TraceToolResultCards({ results }: { results: unknown[] }) {
  return (
    <div className="space-y-2">
      {results.slice(0, 8).map((raw, index) => {
        const result = isRecord(raw) ? raw : {};
        const ok = Boolean(result.ok);
        return (
          <div key={`${String(result.name || "result")}-${index}`} className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-semibold text-slate-900">{String(result.name || "tool")}</span>
              <Badge className={ok ? "border-emerald-200 bg-white text-emerald-700" : "border-rose-200 bg-white text-rose-700"}>{ok ? "ok" : "failed"}</Badge>
              {result.result_shape ? <span className="text-slate-500">{String(result.result_shape)}</span> : null}
              {result.result_count !== undefined ? <span className="text-slate-500">count={String(result.result_count)}</span> : null}
            </div>
            {result.error ? <div className="mt-1 text-rose-700">{String(result.error)}</div> : null}
            {Array.isArray(result.warnings) && result.warnings.length ? <div className="mt-1 text-amber-700">{result.warnings.map(String).join("；")}</div> : null}
          </div>
        );
      })}
    </div>
  );
}

function TraceClaimCards({ claims }: { claims: unknown[] }) {
  if (!claims.length) return <MutedText text="暂无结构化事实。" />;
  const summary = summarizeClaims(claims);
  return (
    <div className="space-y-3">
      <div className="text-[11px] leading-5 text-slate-500">结构化事实是系统从答案中保留的可校验信息，用来确认数量、姓名、排序和证据是否来自工具结果。</div>
      <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
        <div className="flex flex-wrap items-center gap-2">
          <Badge className="border-slate-200 bg-white text-slate-700">结构化事实总数：{claims.length}</Badge>
          {summary.counts.map((item) => (
            <Badge key={item.label} className="border-slate-200 bg-white text-slate-700">{item.label}：{item.count}</Badge>
          ))}
        </div>
        <div className="mt-3 space-y-2 text-sm">
          {summary.countValues.length ? <TraceClaimSummaryRow label="数量" value={summary.countValues.join("、")} /> : null}
          {summary.names.length ? <TraceClaimSummaryRow label="候选人" value={summary.names.join("、")} /> : null}
          {summary.rankings.length ? <TraceClaimSummaryRow label="排序" value={summary.rankings.join("；")} /> : null}
          {summary.evidence.length ? <TraceClaimSummaryRow label="证据" value={summary.evidence.join("；")} /> : null}
          {summary.profiles.length ? <TraceClaimSummaryRow label="档案" value={summary.profiles.join("、")} /> : null}
          {summary.comparisons.length ? <TraceClaimSummaryRow label="对比" value={summary.comparisons.join("、")} /> : null}
          {summary.others.length ? <TraceClaimSummaryRow label="其他" value={summary.others.join("；")} /> : null}
        </div>
      </div>
      <details className="rounded-md border border-slate-200 bg-white/80 px-3 py-2">
        <summary className="cursor-pointer font-semibold text-slate-900">查看完整结构化事实</summary>
        <div className="mt-2 space-y-2">
          {summary.records.map((claim, index) => (
            <div key={`${claim.type}-${index}`} className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2">
              <div className="flex flex-wrap items-center gap-2">
                <Badge>{claimTypeLabel(claim.type)}</Badge>
                <span className="font-semibold text-slate-900">{claim.subject || claim.text || "-"}</span>
              </div>
              {claim.value !== undefined ? <div className="mt-1 text-slate-600">值：{formatInlineTraceValue(claim.value)}</div> : null}
              {claim.supportedBy.length ? <div className="mt-1 text-slate-500">支持工具：{claim.supportedBy.join("、")}</div> : null}
              {claim.evidenceIds.length ? <div className="mt-1 break-all text-slate-500">证据：{claim.evidenceIds.join("、")}</div> : null}
            </div>
          ))}
        </div>
        <pre className="mt-3 max-h-72 overflow-auto whitespace-pre-wrap break-words rounded bg-slate-950 p-3 text-[11px] leading-5 text-slate-100">
          {formatPrettyJson(claims)}
        </pre>
      </details>
    </div>
  );
}

function TraceClaimSummaryRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid gap-1 sm:grid-cols-[88px_minmax(0,1fr)]">
      <div className="font-semibold text-slate-700">{label}</div>
      <div className="break-words text-slate-900">{value}</div>
    </div>
  );
}

type TraceClaimRecord = {
  type: string;
  subject: string;
  text: string;
  value?: unknown;
  supportedBy: string[];
  evidenceIds: string[];
};

function summarizeClaims(claims: unknown[]) {
  const records: TraceClaimRecord[] = claims.map((raw) => {
    const claim = isRecord(raw) ? raw : {};
    return {
      type: String(claim.type || "other"),
      subject: String(claim.subject || ""),
      text: String(claim.text || ""),
      value: claim.value,
      supportedBy: Array.isArray(claim.supported_by) ? claim.supported_by.map(String) : [],
      evidenceIds: Array.isArray(claim.evidence_ids) ? claim.evidence_ids.map(String) : [],
    };
  });
  const byType = (type: string) => records.filter((claim) => claim.type === type);
  const countClaims = byType("count");
  const nameClaims = byType("name");
  const rankingClaims = byType("ranking");
  const evidenceClaims = byType("evidence");
  const profileClaims = byType("profile");
  const comparisonClaims = byType("comparison");
  const knownTypes = new Set(["count", "name", "ranking", "evidence", "profile", "comparison"]);
  const otherClaims = records.filter((claim) => !knownTypes.has(claim.type));
  return {
    records,
    counts: [
      { label: "数量事实", count: countClaims.length },
      { label: "候选人姓名事实", count: nameClaims.length },
      { label: "证据事实", count: evidenceClaims.length },
      { label: "排序事实", count: rankingClaims.length },
      { label: "其他事实", count: profileClaims.length + comparisonClaims.length + otherClaims.length },
    ],
    countValues: countClaims.map((claim) => formatInlineTraceValue(claim.value ?? claim.text)).filter(Boolean),
    names: nameClaims.map(claimDisplayName).filter(Boolean),
    rankings: rankingClaims.map((claim) => {
      const value = isRecord(claim.value) ? claim.value : {};
      const rank = value.rank !== undefined ? `第${String(value.rank)}名` : "排序";
      const score = value.score !== undefined ? `，分数 ${String(value.score)}` : "";
      return `${rank}：${claimDisplayName(claim)}${score}`;
    }).filter(Boolean),
    evidence: evidenceClaims.map((claim) => {
      const subject = claimDisplayName(claim);
      return subject ? `${subject}：${claim.text || "证据"}` : claim.text || "证据";
    }).filter(Boolean),
    profiles: profileClaims.map(claimDisplayName).filter(Boolean),
    comparisons: comparisonClaims.map(claimDisplayName).filter(Boolean),
    others: otherClaims.map((claim) => claimDisplayName(claim) || claim.text || claim.type).filter(Boolean),
  };
}

function claimDisplayName(claim: TraceClaimRecord): string {
  return claim.subject || claim.text || formatInlineTraceValue(claim.value);
}

function claimTypeLabel(type: string): string {
  const labels: Record<string, string> = {
    count: "数量事实",
    name: "候选人姓名事实",
    ranking: "排序事实",
    evidence: "证据事实",
    profile: "档案事实",
    comparison: "对比事实",
    other: "其他事实",
  };
  return labels[type] || type;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

function formatInlineTraceValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "-";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) return value.map(formatInlineTraceValue).join("、");
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function formatTraceNodeValue(value: unknown): ReactNode {
  if (value === null || value === undefined || value === "") return <span className="text-slate-400">-</span>;
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    const text = String(value);
    return <span className="break-words">{text.length > 180 ? `${text.slice(0, 177)}...` : text}</span>;
  }
  if (Array.isArray(value)) {
    const visible = value.slice(0, 4);
    const hidden = value.length - visible.length;
    return (
      <div className="space-y-1">
        {visible.map((item, index) => (
          <div key={index} className="rounded bg-slate-50 px-2 py-1">
            {formatTraceNodeValue(item)}
          </div>
        ))}
        {hidden > 0 ? <div className="text-slate-400">+{hidden}</div> : null}
      </div>
    );
  }
  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>).filter(([, item]) => item !== undefined && item !== null && item !== "");
    if (!entries.length) return <span className="text-slate-400">-</span>;
    return (
      <div className="space-y-1">
        {entries.slice(0, 5).map(([key, item]) => (
          <div key={key} className="grid min-w-0 grid-cols-[104px_minmax(0,1fr)] gap-2 rounded bg-slate-50 px-2 py-1">
            <span className="truncate text-slate-500">{key}</span>
            <div className="min-w-0">{formatTraceNodeValue(item)}</div>
          </div>
        ))}
        {entries.length > 5 ? <div className="text-slate-400">+{entries.length - 5}</div> : null}
      </div>
    );
  }
  return <span>{String(value)}</span>;
}

function CompilerDecisionPanel({ response }: { response?: QAAskResponse }) {
  const decision = response?.trace?.compiler_decision;
  const rows = decision?.hint_tool_decisions || [];
  if (!decision || (!rows.length && !(decision.final_tool_calls || []).length)) return null;
  const sourceLabel = decision.compiler_source === "template" ? "template" : decision.compiler_source === "generic" ? "generic" : decision.compiler_source || "-";
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-xs font-semibold uppercase text-slate-500">Compiler Hint Selection</div>
        <span className="text-xs text-slate-500">配置模式：{decision.compiler_config_mode || decision.compiler_mode || "-"}</span>
      </div>
      <div className="rounded-lg border border-slate-200 bg-white p-3">
        <div className="grid gap-2 text-xs leading-5 text-slate-500 sm:grid-cols-2">
          <div>实际策略：{decision.compiler_strategy || "-"}</div>
          <div>来源：{sourceLabel}</div>
        </div>
        <div className="mt-2 text-xs leading-5 text-slate-500">{decision.selection_rule || "source contract > workflow/template > allowed tools > confidence tie-break"}</div>
        {rows.length ? (
          <div className="mt-3 overflow-x-auto">
            <table className="w-full min-w-[760px] text-left text-xs">
              <thead className="text-slate-500">
                <tr className="border-b border-slate-200">
                  <th className="py-2 pr-3 font-medium">Tool</th>
                  <th className="py-2 pr-3 font-medium">Decision</th>
                  <th className="py-2 pr-3 font-medium">Confidence</th>
                  <th className="py-2 pr-3 font-medium">Intent</th>
                  <th className="py-2 pr-3 font-medium">Reason</th>
                  <th className="py-2 pr-3 font-medium">Artifact</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row, index) => (
                  <tr key={`${row.tool}-${index}`} className="border-b border-slate-100 last:border-0">
                    <td className="py-2 pr-3 font-medium text-slate-900">{row.tool}</td>
                    <td className="py-2 pr-3"><Badge>{row.decision || "-"}</Badge></td>
                    <td className="py-2 pr-3 text-slate-600">{formatHintConfidence(row.confidence, row.source)}</td>
                    <td className="py-2 pr-3 text-slate-600">{(row.intents || []).join("、") || "-"}</td>
                    <td className="py-2 pr-3 text-slate-600">{row.reason || "-"}</td>
                    <td className="py-2 pr-3 text-slate-600">{row.artifact_id || "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function TraceJsonPanel({ title, value, maxHeightClass = "max-h-[520px]" }: { title: string; value?: unknown; maxHeightClass?: string }) {
  if (!value) {
    return (
      <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs text-slate-500">
        <div className="font-semibold uppercase tracking-wide">{title}</div>
        <div className="mt-2">暂无数据</div>
      </div>
    );
  }
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3">
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</div>
      <pre className={`mt-2 ${maxHeightClass} overflow-auto rounded-md bg-slate-950 p-3 text-[11px] leading-5 text-slate-100`}>
        {formatPrettyJson(value)}
      </pre>
    </div>
  );
}

function NavButton({ icon, label, active, onClick }: { icon: ReactNode; label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={`mb-1 flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition ${
        active ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
      }`}
    >
      {icon}
      {label}
    </button>
  );
}

function InfoCell({ label, value }: { label: string; value?: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-3">
      <div className="text-xs font-medium text-slate-500">{label}</div>
      <div className="mt-1 break-words text-sm font-medium text-slate-900">{value || "未填写"}</div>
    </div>
  );
}

function WorkRow({ item }: { item: WorkExperience }) {
  const workDate = dateRange(item.start_date, item.end_date) || "时间未抽取";
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3">
      <div className="flex flex-wrap items-center gap-2">
        <BriefcaseBusiness className="h-4 w-4 text-slate-400" />
        <span className="font-medium text-slate-900">{item.company_name || "未标注公司"}</span>
        <span className="text-sm text-slate-500">{item.job_title_raw}</span>
      </div>
      <div className="mt-2 text-sm text-slate-500">{workDate}</div>
      {item.raw_line ? <div className="mt-2 text-sm leading-6 text-slate-700">{item.raw_line}</div> : null}
    </div>
  );
}

function EducationRow({ item }: { item: EducationExperience }) {
  const educationMeta = [
    item.degree || "学历未抽取",
    item.major || "专业未抽取",
    dateRange(item.start_date, item.end_date) || "时间未抽取",
  ];
  return (
    <div className="rounded-lg border border-slate-200 p-3">
      <div className="font-medium text-slate-900">{item.school_name || "未标注学校"}</div>
      <div className="mt-1 text-sm text-slate-500">{educationMeta.join(" · ")}</div>
    </div>
  );
}

function ProjectRow({ project, evidence }: { project: Project; evidence?: ClassifiedProjects["evidence_chunks"][number] }) {
  const body = evidence?.chunk_text || evidence?.project_summary || "";
  const origin = evidence?.evidence_origin === "chroma" ? "Chroma evidence" : evidence?.evidence_origin === "sql_fallback" ? "SQL fallback" : "";
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="font-medium text-slate-900">{project.project_name_raw || "未命名项目"}</div>
          <div className="mt-1 text-sm text-slate-500">
            {[project.organization_raw, project.date_range_raw, project.role_raw || project.role_normalized].filter(Boolean).join(" · ") || "项目"}
          </div>
        </div>
        {origin ? <Badge className={origin === "Chroma evidence" ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-amber-200 bg-amber-50 text-amber-700"}>{origin}</Badge> : null}
      </div>
      {body ? <div className="mt-3 whitespace-pre-wrap text-sm leading-6 text-slate-700">{body}</div> : null}
      {evidence?.vector_id ? <div className="mt-2 break-all text-xs text-slate-400">vector_id: {evidence.vector_id}</div> : null}
      <div className="mt-3 flex flex-wrap gap-2">
        {dedupeTags(project.tags).slice(0, 8).map((tag) => (
          <Badge key={`${project.project_id}-${tag.tag_type}-${tag.tag_value}`}>{tag.tag_value}</Badge>
        ))}
      </div>
    </div>
  );
}

function SkillSections({ candidate }: { candidate: CandidateDetail }) {
  const grouped = groupedUniqueTags(candidate);
  return (
    <div className="space-y-3">
      <TagGroup title="技能" tags={grouped.skills} limit={10} />
      <TagGroup title="经验" tags={grouped.experience} limit={6} />
      <TagGroup title="涉及领域" tags={grouped.domains} limit={8} />
      <TagGroup title="语言/证书" tags={[...grouped.languages, ...grouped.certifications]} limit={8} />
    </div>
  );
}

function TagGroup({ title, tags, limit = 8 }: { title: string; tags: Tag[]; limit?: number }) {
  if (!tags.length) return null;
  const visibleTags = tags.slice(0, limit);
  const hiddenCount = Math.max(tags.length - visibleTags.length, 0);
  return (
    <div>
      <div className="mb-2 text-xs font-semibold text-slate-500">{title}</div>
      <div className="flex flex-wrap gap-2">
        {visibleTags.map((tag) => (
          <Badge key={`${title}-${tag.tag_type}-${tag.tag_value}`}>{tag.tag_value}</Badge>
        ))}
        {hiddenCount ? <Badge className="text-slate-500">+{hiddenCount}</Badge> : null}
      </div>
    </div>
  );
}

function TagListBlock({ title, values, fallback }: { title: string; values: string[]; fallback: string }) {
  const visibleValues = values.filter(Boolean).slice(0, 6);
  return (
    <div>
      <div className="mb-2 text-xs font-semibold text-slate-500">{title}</div>
      {visibleValues.length ? (
        <div className="flex flex-wrap gap-2">
          {visibleValues.map((value) => (
            <Badge key={`${title}-${value}`}>{value}</Badge>
          ))}
        </div>
      ) : (
        <MutedText text={fallback} />
      )}
    </div>
  );
}

function CompactTagList({ title, values, fallback, limit }: { title: string; values: string[]; fallback: string; limit: number }) {
  const uniqueValues = dedupeValues(values.filter(Boolean));
  const visibleValues = uniqueValues.slice(0, limit);
  const hiddenCount = Math.max(uniqueValues.length - visibleValues.length, 0);
  return (
    <div className="min-w-0 rounded-lg border border-slate-200 bg-white px-4 py-3">
      <div className="mb-2 text-xs font-semibold text-slate-500">{title}</div>
      {visibleValues.length ? (
        <div className="flex flex-wrap gap-2">
          {visibleValues.map((value) => (
            <Badge key={`${title}-${value}`}>{value}</Badge>
          ))}
          {hiddenCount ? <Badge className="text-slate-500">+{hiddenCount}</Badge> : null}
        </div>
      ) : (
        <MutedText text={fallback} />
      )}
    </div>
  );
}

function SectionLabel({ title, count }: { title: string; count: number }) {
  return (
    <div className="flex items-center justify-between">
      <div className="text-sm font-semibold text-slate-900">{title}</div>
      <Badge>{count}</Badge>
    </div>
  );
}

function projectDisplayEvidence(project: Project, evidenceChunks: ClassifiedProjects["evidence_chunks"]) {
  return evidenceChunks.find((item) => item.project_id === project.project_id || item.project_title === project.project_name_raw);
}

function mergeProjects(...groups: Project[][]) {
  const seen = new Set<string>();
  const output: Project[] = [];
  for (const group of groups) {
    for (const project of group) {
      const key = [
        project.project_name_raw,
        project.organization_raw,
        project.date_range_raw,
        project.role_raw || project.role_normalized,
      ]
        .map(normalizeProjectKeyPart)
        .join("|");
      if (seen.has(key)) continue;
      seen.add(key);
      output.push(project);
    }
  }
  return output;
}

function normalizeProjectKeyPart(value: string) {
  return value.replace(/\s+/g, "").trim().toLowerCase();
}

function SummaryCard({ title, text }: { title: string; text: string }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="text-sm leading-7 text-slate-700">{text || "暂无内容。"}</div>
      </CardContent>
    </Card>
  );
}

function ListBlock({ title, items }: { title: string; items: string[] }) {
  return (
    <div>
      <div className="text-sm font-medium text-slate-900">{title}</div>
      <div className="mt-2 space-y-2">
        {items.length ? items.map((item) => <div key={item} className="text-sm leading-6 text-slate-700">- {item}</div>) : <MutedText text="暂无。" />}
      </div>
    </div>
  );
}

function LoadingRow({ text }: { text: string }) {
  return (
    <div className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600">
      <Loader2 className="h-4 w-4 animate-spin" />
      {text}
    </div>
  );
}

function AccessPasswordPanel({
  value,
  checking,
  onChange,
  onSubmit,
}: {
  value: string;
  checking: boolean;
  onChange: (value: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  return (
    <Card className="border-amber-200 bg-amber-50">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <KeyRound className="h-4 w-4 text-amber-700" />
          访问密码
        </CardTitle>
        <CardDescription className="text-amber-800">
          当前部署已启用简单访问保护，输入密码后才能查看候选人、上传简历和使用 AI 问答。
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form className="flex flex-col gap-3 sm:flex-row" onSubmit={onSubmit}>
          <Input
            type="password"
            value={value}
            onChange={(event) => onChange(event.target.value)}
            placeholder="输入访问密码"
            autoComplete="current-password"
            className="bg-white"
          />
          <Button type="submit" disabled={checking} className="shrink-0">
            {checking ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <KeyRound className="mr-2 h-4 w-4" />}
            解锁
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}

function IngestionProgress({ status }: { status: IngestionStatus | null }) {
  const total = status?.total_files || 0;
  const current = status?.current_index || 0;
  const percent = total ? Math.min(100, Math.round((current / total) * 100)) : 12;
  const messages = status?.recent_messages?.slice(-4) || [];
  const modeLabel = status?.mode === "upload" ? "上传入库进度" : "导入进度";
  const uploadSteps = buildUploadProgressSteps(status);
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm text-slate-700">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <Loader2 className="h-4 w-4 shrink-0 animate-spin text-emerald-600" />
          <span className="font-medium text-slate-900">
            {total ? `${modeLabel} ${current}/${total}` : "正在准备导入"}
          </span>
          {status?.current_file ? <span className="truncate text-slate-500">{status.current_file}</span> : null}
        </div>
        <span className="text-xs text-slate-500">{status?.success_count || 0} 成功 / {status?.error_count || 0} 失败</span>
      </div>
      <div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-100">
        <div className="h-full rounded-full bg-emerald-500 transition-all" style={{ width: `${percent}%` }} />
      </div>
      {status?.mode === "upload" ? (
        <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-6">
          {uploadSteps.map((step) => (
            <div
              key={step.label}
              className={`rounded-md border px-2 py-2 text-xs ${
                step.state === "done"
                  ? "border-emerald-200 bg-emerald-50 text-emerald-800"
                  : step.state === "active"
                    ? "border-sky-200 bg-sky-50 text-sky-800"
                    : step.state === "failed"
                      ? "border-red-200 bg-red-50 text-red-800"
                      : "border-slate-200 bg-slate-50 text-slate-500"
              }`}
            >
              <div className="font-semibold">{step.label}</div>
              <div className="mt-1 leading-4">{step.text}</div>
            </div>
          ))}
        </div>
      ) : null}
      <div className="mt-2 text-sm text-slate-600">{status?.current_step || status?.message || "正在处理简历文件"}</div>
      {status?.error_hint ? (
        <div className="mt-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm leading-6 text-red-700">
          {status.error_hint}
        </div>
      ) : null}
      {messages.length ? (
        <div className="mt-2 space-y-1 text-xs leading-5 text-slate-500">
          {messages.map((message, index) => (
            <div key={`${message}-${index}`}>{message}</div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function buildUploadProgressSteps(status: IngestionStatus | null) {
  const currentStep = `${status?.current_step || ""} ${status?.message || ""}`;
  const failed = Boolean(status?.error_count);
  const done = status?.phase === "done" && !failed;
  const activeIndex = done ? 5 : failed ? 4 : uploadProgressIndex(currentStep);
  const labels = [
    ["上传文件", "浏览器提交文件"],
    ["保存文件", "写入 data/resume/uploads"],
    ["解析文本", "读取简历内容"],
    ["抽取字段", "识别候选人和项目"],
    ["校验写库", "写入 SQLite/Chroma"],
    ["AI 可查询", "刷新候选人和证据"],
  ];
  return labels.map(([label, text], index) => ({
    label,
    text,
    state: failed && index === activeIndex ? "failed" : index < activeIndex || done ? "done" : index === activeIndex ? "active" : "pending",
  }));
}

function uploadProgressIndex(text: string) {
  if (/保存上传文件|已保存上传文件/.test(text)) return 1;
  if (/解析简历文本|解析完成|开始解析上传简历/.test(text)) return 2;
  if (/抽取候选字段|规则抽取完成|LLM\/规则复核/.test(text)) return 3;
  if (/校验结构化结果|写入 SQLite|写库完成|写入审计日志/.test(text)) return 4;
  if (/上传入库完成|可在 AI/.test(text)) return 5;
  return 0;
}

function LlmStatusPanel({ status, onClose }: { status: LlmStatus; onClose: () => void }) {
  const localActive = status.chat_provider === "ollama";
  return (
    <div className={`rounded-lg border px-4 py-3 text-sm ${localActive ? "border-emerald-200 bg-emerald-50 text-emerald-800" : "border-amber-200 bg-amber-50 text-amber-800"}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="font-medium">当前总结模型：{status.display_name}</div>
        <div className="flex items-center gap-2">
          <Badge className={status.available ? "border-emerald-200 bg-white text-emerald-700" : "border-amber-200 bg-white text-amber-700"}>
            {status.available ? "可用" : "不可用"}
          </Badge>
          <button
            type="button"
            onClick={onClose}
            aria-label="关闭总结服务状态"
            className="inline-flex h-7 w-7 items-center justify-center rounded-md border border-current/20 bg-white/70 transition hover:bg-white"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>
      <div className="mt-2 leading-6">{status.message}</div>
    </div>
  );
}

function EmptyState({ title, text }: { title: string; text: string }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>{text}</CardDescription>
      </CardHeader>
    </Card>
  );
}

function MutedText({ text }: { text: string }) {
  return <div className="text-sm text-slate-500">{text}</div>;
}

function dateRange(start: string, end: string) {
  return [start, end].filter(Boolean).join(" - ");
}

function selectKeyEvidenceRefs(response?: QAAskResponse) {
  const refs = (response?.used_evidence_refs || []).filter(isChromaEvidenceRef);
  if (!refs.length) return [];
  const seen = new Set<string>();
  const sorted = [...refs].sort((a, b) => evidencePriority(b) - evidencePriority(a) || (b.strength || 0) - (a.strength || 0));
  const selected: QAEvidenceRef[] = [];
  for (const ref of sorted) {
    const candidateKey = ref.resume_identity || ref.candidate_name || ref.evidence_id;
    if (candidateKey && seen.has(candidateKey)) continue;
    selected.push(ref);
    if (candidateKey) seen.add(candidateKey);
    if (selected.length >= 3) return selected;
  }
  for (const ref of sorted) {
    const key = ref.evidence_id || `${ref.resume_identity}-${ref.project_id}-${ref.text.slice(0, 24)}`;
    if (selected.some((item) => (item.evidence_id || `${item.resume_identity}-${item.project_id}-${item.text.slice(0, 24)}`) === key)) continue;
    selected.push(ref);
    if (selected.length >= 3) break;
  }
  return selected;
}

function isChromaEvidenceRef(ref: QAEvidenceRef) {
  return Boolean(ref.evidence_id) && ["project_experience", "work_experience", "project_evidence"].includes(ref.source_type);
}

function evidencePriority(ref: QAEvidenceRef) {
  if (ref.source_type === "project_experience" || ref.source_type === "project_evidence") return 300;
  if (ref.source_type === "work_experience" || ref.source_type === "work_experiences") return 200;
  if (["project_tags", "domain_tags", "candidate_tags"].includes(ref.source_type)) return 100;
  return 0;
}

function groupEvidenceRefs(refs: QAEvidenceRef[]) {
  const groups: Record<string, QAEvidenceRef[]> = {
    "项目 Chroma evidence": [],
    "工作经历": [],
  };
  for (const ref of refs) {
    if (ref.source_type === "project_experience" || ref.source_type === "project_evidence") groups["项目 Chroma evidence"].push(ref);
    else if (ref.source_type === "work_experience" || ref.source_type === "work_experiences") groups["工作经历"].push(ref);
  }
  return groups;
}

function sourceTypeLabel(sourceType: string) {
  const labels: Record<string, string> = {
    project_experience: "项目经历",
    work_experience: "工作经历",
    project_evidence: "项目证据",
    project_tags: "项目标签",
    domain_tags: "领域标签",
    candidate_tags: "候选人标签",
    work_experiences: "工作经历",
    education_experiences: "教育经历",
  };
  return labels[sourceType] || "证据";
}

function summarizeEvidenceRef(ref: QAEvidenceRef) {
  const subject = ref.candidate_name || "候选人";
  const title = ref.project_title || sourceTypeLabel(ref.source_type);
  const text = cleanEvidenceText(ref.text, title);
  if (!text) return `${subject}的${title}可作为该结论来源，但原始证据文本较少。`;
  const sentence = text.split(/[。；;\n]/)[0] || text;
  const summary = `${subject}在${title}中体现：${sentence}`;
  return summary.length > 80 ? `${summary.slice(0, 77).replace(/[，。；、\s]+$/, "")}...` : summary;
}

function cleanEvidenceText(value: string, title: string) {
  let text = value.replace(/\s+/g, " ").trim();
  text = text.replace(/^#+\s*/, "").replace(/^[-•●\s]+/, "");
  const cleanTitle = title.replace(/\s+/g, " ").trim();
  for (const prefix of [cleanTitle, `${cleanTitle} -`, `${cleanTitle}：`, `${cleanTitle}:`]) {
    if (cleanTitle && text.startsWith(prefix)) {
      text = text.slice(prefix.length).replace(/^[\s\-：:]+/, "");
      break;
    }
  }
  return text.replace(/\s*[\-•●]\s*/g, "，").replace(/\s+/g, " ").trim();
}

function dedupeTags(tags: Tag[]) {
  const seen = new Set<string>();
  const output: Tag[] = [];
  for (const tag of tags) {
    const key = normalizeTagValue(tag.tag_value);
    if (!key || seen.has(key)) continue;
    seen.add(key);
    output.push(tag);
  }
  return output;
}

function groupedUniqueTags(candidate: CandidateDetail) {
  const seen = new Set<string>();
  const take = (tags: Tag[]) => {
    const output: Tag[] = [];
    for (const tag of tags) {
      const key = normalizeTagValue(tag.tag_value);
      if (!key || seen.has(key)) continue;
      seen.add(key);
      output.push(tag);
    }
    return output;
  };
  const skills = take(candidate.tags.filter((tag) => tag.tag_type === "skill"));
  return {
    skills: skills.length ? skills : take(candidate.skills),
    experience: take(candidate.tags.filter((tag) => tag.tag_type === "experience")),
    domains: take(candidate.tags.filter((tag) => tag.tag_type === "domain")),
    languages: take(candidate.languages),
    certifications: take(candidate.certifications_or_scores),
  };
}

function normalizeWorkProfile(candidate: CandidateDetail): WorkProfile {
  const grouped = groupedUniqueTags(candidate);
  const fallbackYears = estimateFrontendWorkYears(candidate.work_experiences);
  return {
    years_label: candidate.work_profile?.years_label || formatFrontendYears(fallbackYears),
    total_years: candidate.work_profile?.total_years || fallbackYears,
    confidence_label: candidate.work_profile?.confidence_label || (fallbackYears > 0 ? "中" : "待复核"),
    domains: candidate.work_profile?.domains?.length
      ? candidate.work_profile.domains
      : [...grouped.experience, ...grouped.domains].map((tag) => tag.tag_value),
    roles: candidate.work_profile?.roles?.length
      ? candidate.work_profile.roles
      : dedupeValues(candidate.work_experiences.map((item) => item.job_title_raw)),
    companies: candidate.work_profile?.companies?.length
      ? candidate.work_profile.companies
      : dedupeValues(candidate.work_experiences.map((item) => item.company_name)),
  };
}

function estimateFrontendWorkYears(workExperiences: WorkExperience[]) {
  const intervals = workExperiences
    .map((item) => {
      const start = monthIndex(item.start_date);
      const end = monthIndex(item.end_date) ?? (isPresentDate(item.end_date) ? new Date().getFullYear() * 12 + new Date().getMonth() + 1 : start);
      if (!start || !end) return null;
      return start <= end ? [start, end] : [end, start];
    })
    .filter((item): item is number[] => Boolean(item))
    .sort((a, b) => a[0] - b[0]);
  if (!intervals.length) return 0;
  const merged: number[][] = [];
  for (const [start, end] of intervals) {
    const last = merged[merged.length - 1];
    if (!last || start > last[1] + 1) {
      merged.push([start, end]);
    } else {
      last[1] = Math.max(last[1], end);
    }
  }
  const months = merged.reduce((sum, [start, end]) => sum + end - start + 1, 0);
  return Math.round((months / 12) * 10) / 10;
}

function monthIndex(value: string) {
  const match = value.match(/(19|20)\d{2}(?:[-./年](0?[1-9]|1[0-2]))?/);
  if (!match) return 0;
  const year = Number(match[0].slice(0, 4));
  const monthMatch = match[0].match(/[-./年](0?[1-9]|1[0-2])/);
  const month = monthMatch ? Number(monthMatch[1]) : 1;
  return year * 12 + month;
}

function isPresentDate(value: string) {
  return /至今|present|current|now/i.test(value);
}

function formatFrontendYears(years: number) {
  if (!years) return "年限待复核";
  if (years < 1) return "不足 1 年";
  const whole = Math.floor(years);
  return years - whole >= 0.5 ? `${whole}.5 年` : `${whole} 年`;
}

function formatUnknownValue(value: unknown) {
  if (value === null || value === undefined || value === "") return "";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function formatHintConfidence(value: number | undefined, source?: string) {
  if (typeof value !== "number") return "-";
  const suffix = source === "legacy_default" ? " default" : "";
  return `${value.toFixed(2)}${suffix}`;
}

function formatPrettyJson(value: unknown) {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function traceStepStatus(step: TraceStep, routeEvents: TraceRouteEvent[]): TraceNodeStatus {
  const relatedRoutes = routeEvents.filter((event) => event.route_from === step.node);
  const routeTargets = relatedRoutes.map((event) => event.route_to || "");
  if (step.status === "failed" || (step.errors || []).length) return "failed";
  if (step.repair_action || step.fallback_reason || routeTargets.some((target) => target === "repair" || target === "fallback")) return "repair";
  if (routeTargets.includes("clarify")) return "clarification";
  if (step.node === "final") return "final";
  return "ok";
}

function traceIssueSummaries(step: TraceStep, status: TraceNodeStatus, routes: TraceRouteEvent[]) {
  const summaries: string[] = [];
  const issueRoutes = routes.filter((event) => ["repair", "fallback", "clarify", "fail"].includes(event.route_to || ""));
  for (const event of issueRoutes) {
    const reason = event.reason || event.errors?.[0] || "-";
    summaries.push(`${event.route_from || step.node || "node"} -> ${event.route_to || "-"}：${reason}`);
  }
  if (!summaries.length && status !== "ok" && status !== "final") {
    const reason = step.error_category || step.fallback_reason || step.repair_reason || step.errors?.[0] || step.warnings?.[0] || step.summary || "-";
    summaries.push(`${step.node || "node"}：${reason}`);
  }
  return summaries;
}

function traceStatusBadgeClass(status: TraceNodeStatus) {
  if (status === "failed") return "border-rose-200 bg-rose-50 text-rose-700";
  if (status === "repair") return "border-amber-200 bg-amber-50 text-amber-700";
  if (status === "clarification") return "border-sky-200 bg-sky-50 text-sky-700";
  if (status === "final") return "border-emerald-200 bg-emerald-50 text-emerald-700";
  return "border-slate-200 bg-white text-slate-600";
}

function isLayoutAuditWarning(value: string) {
  return /^answer_layout(_source)?:/.test(value);
}

function graphRows(nodeIds: string[]) {
  const preferred = [
    ["router", "condition_normalizer", "planner", "plan_compiler", "plan_validator"],
    ["", "", "", "", "executor"],
    ["plan_repair", "", "", "", "execution_validator"],
    ["execution_repair", "", "aggregator", "answer_validator", "final"],
    ["", "", "answer_rewrite", "rule_answer_fallback", ""],
    ["clarification", "", "", "", "fail"],
  ];
  const known = new Set(preferred.flat().filter(Boolean));
  const extras = nodeIds.filter((id) => !known.has(id));
  return extras.length ? [...preferred, extras] : preferred;
}

function graphNodeClass(status: string, selected: boolean) {
  const selectedClass = selected ? "ring-2 ring-slate-900" : "";
  if (status === "final") return `${selectedClass} border-emerald-300 bg-emerald-50`;
  if (status === "failed") return `${selectedClass} border-rose-300 bg-rose-50`;
  if (status === "repair") return `${selectedClass} border-amber-300 bg-amber-50`;
  if (status === "clarification") return `${selectedClass} border-sky-300 bg-sky-50`;
  if (status === "ok") return `${selectedClass} border-slate-300 bg-white`;
  return `${selectedClass} border-slate-200 bg-slate-100 opacity-60`;
}

function diagnosisClass(level?: string) {
  if (level === "error") return "border-rose-200 bg-rose-50 text-rose-800";
  if (level === "warning") return "border-amber-200 bg-amber-50 text-amber-800";
  if (level === "clarification") return "border-sky-200 bg-sky-50 text-sky-800";
  if (level === "info") return "border-slate-200 bg-slate-50 text-slate-700";
  if (level === "ok") return "border-emerald-200 bg-emerald-50 text-emerald-800";
  return "border-slate-200 bg-white text-slate-700";
}

function dedupeValues(values: string[]) {
  const seen = new Set<string>();
  const output: string[] = [];
  for (const value of values) {
    const key = value.replace(/\s+/g, "").trim().toLowerCase();
    if (!key || seen.has(key)) continue;
    seen.add(key);
    output.push(value);
  }
  return output;
}

function normalizeTagValue(value: string) {
  return value.trim().toLowerCase();
}


function buildIngestDetails(result: IngestionResponse) {
  const resetItems = result.reset_summary?.enabled
    ? [
        `已清空旧入库数据：删除 ${result.reset_summary.removed?.length || 0} 项 SQLite/Chroma 存储。`,
        result.reset_summary.uploads_removed ? `已删除 ${result.reset_summary.uploads_removed.length} 个上传文件。` : "",
      ].filter(Boolean)
    : [];
  if (!result.results.length) {
    return [...resetItems, `扫描目录：${result.directory}`];
  }
  return [...resetItems, ...result.results.map((item) => {
    const fileName = item.file.split("/").pop() || item.file;
    if (item.status === "error") {
      return `${fileName}: 失败，${item.error || "未知错误"}`;
    }
    const mode = ingestResultMode(item);
    const blocked = item.storage_blocked_message || (item.storage_blocked_reason ? "项目边界未可信完成，项目未入库。" : "");
    const blockedText = blocked ? `，${blocked}` : "";
    return `${fileName}: ${mode}，${item.name || "未命名"}，工作 ${item.work_count ?? 0}，教育 ${item.education_count ?? 0}，项目 ${item.project_count ?? 0}${blockedText}`;
  })];
}

function hasIngestionSuccess(result: IngestionResponse) {
  return result.success_count > 0 && result.results.some((item) => item.status === "ok");
}

function hasIngestionFailure(result: IngestionResponse) {
  return result.error_count > 0 || result.results.some((item) => item.status === "error");
}

function ingestResultMode(item: IngestionResult) {
  if (item.merged_existing_candidate || ["email", "phone", "name"].includes(String(item.identity_match_source || ""))) {
    const source = String(item.identity_match_source || "");
    const sourceLabel = source === "email" ? "邮箱" : source === "phone" ? "手机号" : source === "name" ? "姓名" : "身份";
    return `已更新同一候选人（${sourceLabel}匹配）`;
  }
  if (item.replaced_existing_resume) return "已刷新";
  return "已新增";
}

function normalizeError(error: unknown) {
  const message = error instanceof Error ? error.message : String(error);
  if (isUnauthorizedError(error)) {
    return "访问密码无效或缺失。";
  }
  if (/failed to fetch|fetch failed|load failed|networkerror/i.test(message)) {
    return "无法连接后端 API。请先启动：./.venv/bin/uvicorn resume_query_api.main:app --host 127.0.0.1 --port 8000";
  }
  if (message.includes("已有 resume 导入任务正在运行")) {
    return "已有 resume 导入任务正在运行，请等当前任务结束后再试。";
  }
  return message;
}

function isUnauthorizedError(error: unknown) {
  const message = error instanceof Error ? error.message : String(error);
  return message.startsWith("UNAUTHORIZED:");
}
