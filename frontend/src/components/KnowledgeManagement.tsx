"use client";

import { FormEvent, type ReactNode, useCallback, useEffect, useState } from "react";
import { AlertCircle, BookOpen, CheckCircle2, Database, ExternalLink, FileClock, FileUp, LoaderCircle, Play, RefreshCw, RotateCcw, Search, Send, SlidersHorizontal, X } from "lucide-react";
import Pagination from "@/components/Pagination";
import * as api from "@/lib/api";
import { formatAppDateTime } from "@/lib/time";
import type { KnowledgeCatalogSyncItem, KnowledgeCatalogSyncRun, KnowledgeDocumentVersionListItem, KnowledgeRetrievalStrategy, KnowledgeSearchResult, KnowledgeSourceType, KnowledgeVersion } from "@/types";

const SOURCE_TYPES: Array<{ value: KnowledgeSourceType; label: string }> = [
  { value: "methodology", label: "行业方法论" },
  { value: "benchmark_rule", label: "基准与规则" },
  { value: "case_sop", label: "脱敏案例与 SOP" },
];

const RETRIEVAL_STRATEGIES: Array<{ value: KnowledgeRetrievalStrategy; label: string }> = [
  { value: "strict", label: "严格全场景匹配" },
  { value: "progressive", label: "分级放宽" },
  { value: "industry_only", label: "仅行业匹配" },
  { value: "unfiltered", label: "不使用场景过滤" },
  { value: "scene_boost", label: "场景排序加分" },
];

type KnowledgeTab = "upload" | "search" | "versions" | "sync";

const KNOWLEDGE_TABS = [
  { id: "upload", label: "文档上传", icon: FileUp },
  { id: "search", label: "检索", icon: Search },
  { id: "versions", label: "资料版本", icon: FileClock },
  { id: "sync", label: "内置行业文档同步", icon: Database },
] satisfies Array<{ id: KnowledgeTab; label: string; icon: typeof FileUp }>;

export default function KnowledgeManagement() {
  const [activeTab, setActiveTab] = useState<KnowledgeTab>("upload");
  const [versions, setVersions] = useState<KnowledgeDocumentVersionListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [processingVersion, setProcessingVersion] = useState<string | null>(null);
  const [replacementFor, setReplacementFor] = useState<KnowledgeDocumentVersionListItem | null>(null);
  const [title, setTitle] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [sourceType, setSourceType] = useState<KnowledgeSourceType>("methodology");
  const [industryTags, setIndustryTags] = useState("");
  const [subIndustryTags, setSubIndustryTags] = useState("");
  const [businessModeTags, setBusinessModeTags] = useState("");
  const [operatingStageTags, setOperatingStageTags] = useState("");
  const [syncRun, setSyncRun] = useState<KnowledgeCatalogSyncRun | null>(null);
  const [syncLoading, setSyncLoading] = useState(true);
  const [syncAction, setSyncAction] = useState<"start" | "retry" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchLimit, setSearchLimit] = useState(10);
  const [searchResults, setSearchResults] = useState<KnowledgeSearchResult[]>([]);
  const [searchLoading, setSearchLoading] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [searched, setSearched] = useState(false);
  const [retrievalStrategy, setRetrievalStrategy] = useState<KnowledgeRetrievalStrategy | null>(null);
  const [retrievalStrategySaving, setRetrievalStrategySaving] = useState(false);

  const loadVersions = useCallback(async (targetPage = page, targetPageSize = pageSize) => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.listKnowledgeDocumentVersions(targetPage, targetPageSize);
      setVersions(result.items);
      setTotal(result.total);
    } catch (err) {
      setError(readableError(err));
    } finally {
      setLoading(false);
    }
  }, [page, pageSize]);

  const loadSyncRun = useCallback(async () => {
    try {
      const run = await api.getLatestIndustrySync();
      setSyncRun(run);
      return run;
    } catch (err) {
      setError(readableError(err));
      return null;
    } finally {
      setSyncLoading(false);
    }
  }, []);

  const loadRetrievalStrategy = useCallback(async () => {
    try {
      const policy = await api.getKnowledgeRetrievalPolicy();
      setRetrievalStrategy(policy.strategy);
    } catch (err) {
      setError(readableError(err));
    }
  }, []);

  useEffect(() => {
    void loadVersions();
    void loadSyncRun();
    void loadRetrievalStrategy();
  }, [loadRetrievalStrategy, loadSyncRun, loadVersions]);

  useEffect(() => {
    if (!syncRun || !isSyncActive(syncRun.state)) return;
    const timer = window.setInterval(() => {
      void loadSyncRun().then((next) => {
        if (next && !isSyncActive(next.state)) void loadVersions();
      });
    }, 2000);
    return () => window.clearInterval(timer);
  }, [loadSyncRun, loadVersions, syncRun]);

  function resetForm() {
    setReplacementFor(null);
    setTitle("");
    setFile(null);
    setSourceType("methodology");
    setIndustryTags("");
    setSubIndustryTags("");
    setBusinessModeTags("");
    setOperatingStageTags("");
  }

  function startReplacement(item: KnowledgeDocumentVersionListItem) {
    setReplacementFor(item);
    setTitle(item.document_title);
    setSourceType(item.version.source_type);
    setIndustryTags(item.version.industry_tags.join(", "));
    setSubIndustryTags(item.version.sub_industry_tags.join(", "));
    setBusinessModeTags(item.version.business_mode_tags.join(", "));
    setOperatingStageTags(item.version.operating_stage_tags.join(", "));
    setFile(null);
    setError(null);
    setActiveTab("upload");
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!file || submitting || (!replacementFor && !title.trim())) return;
    setSubmitting(true);
    setError(null);
    const payload = { title, sourceType, file, industryTags, subIndustryTags, businessModeTags, operatingStageTags };
    try {
      if (replacementFor) await api.createKnowledgeDocumentVersion(replacementFor.document_id, payload);
      else await api.createKnowledgeDocument(payload);
      resetForm();
      if (page === 1) await loadVersions(1, pageSize);
      else setPage(1);
    } catch (err) {
      setError(readableError(err));
    } finally {
      setSubmitting(false);
    }
  }

  async function process(version: KnowledgeVersion, action: "publish" | "revoke" | "retry") {
    if (action === "revoke" && !window.confirm("撤回后不会再参与新检索，历史报告也不再展示该来源详情。确认继续吗？")) return;
    setProcessingVersion(version.id);
    setError(null);
    try {
      if (action === "publish") await api.publishKnowledgeVersion(version.id);
      if (action === "revoke") await api.revokeKnowledgeVersion(version.id);
      if (action === "retry") await api.retryKnowledgeIngestion(version.id);
      await loadVersions();
    } catch (err) {
      setError(readableError(err));
    } finally {
      setProcessingVersion(null);
    }
  }

  async function startSync() {
    setSyncAction("start");
    setError(null);
    try {
      setSyncRun(await api.startIndustrySync());
    } catch (err) {
      setError(readableError(err));
    } finally {
      setSyncAction(null);
    }
  }

  async function runSearch(event: FormEvent) {
    event.preventDefault();
    const query = searchQuery.trim();
    if (!query || searchLoading) return;
    const limit = Math.min(100, Math.max(1, Math.trunc(searchLimit || 10)));
    setSearchLimit(limit);
    setSearchLoading(true);
    setSearchError(null);
    setSearched(true);
    try {
      setSearchResults(await api.searchKnowledge(query, limit));
    } catch (err) {
      setSearchResults([]);
      setSearchError(readableError(err));
    } finally {
      setSearchLoading(false);
    }
  }

  async function updateRetrievalStrategy(next: KnowledgeRetrievalStrategy) {
    if (!retrievalStrategy || retrievalStrategySaving || next === retrievalStrategy) return;
    const previous = retrievalStrategy;
    setRetrievalStrategy(next);
    setRetrievalStrategySaving(true);
    setError(null);
    try {
      const policy = await api.updateKnowledgeRetrievalPolicy(next);
      setRetrievalStrategy(policy.strategy);
    } catch (err) {
      setRetrievalStrategy(previous);
      setError(readableError(err));
    } finally {
      setRetrievalStrategySaving(false);
    }
  }

  async function retryFailedSync() {
    if (!syncRun) return;
    setSyncAction("retry");
    setError(null);
    try {
      setSyncRun(await api.retryFailedIndustrySync(syncRun.id));
    } catch (err) {
      setError(readableError(err));
    } finally {
      setSyncAction(null);
    }
  }

  return (
    <section>
      <header className="flex items-end justify-between border-b border-slate-200 pb-6">
        <div className="flex items-start gap-4">
          <div className="flex h-11 w-11 items-center justify-center rounded-md bg-blue-600 text-white shadow-sm">
            <BookOpen className="h-5 w-5" />
          </div>
          <div>
            <p className="text-xs font-semibold text-blue-700">KNOWLEDGE BASE</p>
            <h2 className="mt-1 text-xl font-semibold text-slate-950">行业知识库</h2>
            <p className="mt-1 text-sm text-slate-500">管理检索资料、版本状态与内置行业文档同步。</p>
          </div>
        </div>
          <label className="flex items-center gap-2 text-sm font-medium text-slate-700" htmlFor="knowledge-retrieval-strategy">
            <SlidersHorizontal className="h-4 w-4 text-slate-500" />
            <span>检索策略</span>
            <select
              id="knowledge-retrieval-strategy"
              value={retrievalStrategy ?? ""}
              onChange={(event) => void updateRetrievalStrategy(event.target.value as KnowledgeRetrievalStrategy)}
              disabled={retrievalStrategy === null || retrievalStrategySaving}
              className="h-9 min-w-44 rounded-md border border-slate-300 bg-white px-2 text-sm font-normal outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-100 disabled:cursor-not-allowed disabled:bg-slate-50"
            >
              {retrievalStrategy === null && <option value="">加载中</option>}
              {RETRIEVAL_STRATEGIES.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
            </select>
          </label>
      </header>

      <div className="mt-6 overflow-x-auto border-b border-slate-200">
        <div role="tablist" aria-label="知识库功能" className="flex min-w-max gap-6">
          {KNOWLEDGE_TABS.map(({ id, label, icon: Icon }) => {
            const active = activeTab === id;
            return (
              <button
                key={id}
                id={`knowledge-tab-${id}`}
                type="button"
                role="tab"
                aria-selected={active}
                aria-controls={`knowledge-panel-${id}`}
                onClick={() => setActiveTab(id)}
                className={`flex h-12 items-center gap-2 border-b-2 px-1 text-sm font-medium transition-colors ${
                  active
                    ? "border-blue-600 text-blue-700"
                    : "border-transparent text-slate-500 hover:border-slate-300 hover:text-slate-800"
                }`}
              >
                <Icon className="h-4 w-4" />
                <span>{label}</span>
              </button>
            );
          })}
        </div>
      </div>

      {error && <div role="alert" className="mt-6 border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}

      <div id="knowledge-panel-upload" role="tabpanel" aria-labelledby="knowledge-tab-upload" hidden={activeTab !== "upload"} className="mt-6">
        <form onSubmit={submit} className="max-w-2xl space-y-3 rounded-md border border-gray-200 bg-white p-5 shadow-sm">
          <div className="flex items-center justify-between gap-3">
            <h3 className="text-sm font-semibold">{replacementFor ? `上传 ${replacementFor.document_title} 的新版本` : "上传资料"}</h3>
            {replacementFor && (
              <button type="button" onClick={resetForm} title="取消新版本上传" aria-label="取消新版本上传" className="flex h-8 w-8 items-center justify-center rounded-md text-gray-500 hover:bg-gray-100">
                <X className="h-4 w-4" />
              </button>
            )}
          </div>
          {!replacementFor && <TextInput label="资料标题" value={title} onChange={setTitle} placeholder="例如：外卖转化漏斗诊断方法" />}
          <div>
            <label className="mb-1.5 block text-sm font-medium text-gray-700" htmlFor="knowledge-file">原件</label>
            <input id="knowledge-file" type="file" accept=".docx,.md,.markdown,.txt" onChange={(event) => setFile(event.target.files?.[0] ?? null)} className="block w-full text-sm text-gray-600 file:mr-3 file:rounded file:border-0 file:bg-gray-100 file:px-3 file:py-2 file:text-sm file:font-medium file:text-gray-700 hover:file:bg-gray-200" />
            <p className="mt-1 text-xs text-gray-400">DOCX、Markdown 或 TXT，最大 20 MB</p>
          </div>
          <div>
            <label className="mb-1.5 block text-sm font-medium text-gray-700" htmlFor="knowledge-source">资料类型</label>
            <select id="knowledge-source" value={sourceType} onChange={(event) => setSourceType(event.target.value as KnowledgeSourceType)} className="h-10 w-full rounded-md border border-gray-300 bg-white px-3 text-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100">
              {SOURCE_TYPES.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
            </select>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <TextInput label="行业标签" value={industryTags} onChange={setIndustryTags} placeholder="餐饮, 电商" />
            <TextInput label="子行业标签" value={subIndustryTags} onChange={setSubIndustryTags} placeholder="火锅, 茶饮" />
            <TextInput label="业务模式标签" value={businessModeTags} onChange={setBusinessModeTags} placeholder="外卖, 到店" />
            <TextInput label="经营阶段标签" value={operatingStageTags} onChange={setOperatingStageTags} placeholder="增长, 成熟" />
          </div>
          <button type="submit" disabled={submitting || !file || (!replacementFor && !title.trim())} className="flex h-10 w-full items-center justify-center gap-2 rounded-md bg-gray-900 px-4 text-sm font-medium text-white hover:bg-gray-800 disabled:cursor-not-allowed disabled:opacity-50">
            {submitting ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <FileUp className="h-4 w-4" />}
            <span>{submitting ? "正在上传..." : replacementFor ? "创建新版本" : "上传并解析"}</span>
          </button>
        </form>
      </div>

      <div id="knowledge-panel-search" role="tabpanel" aria-labelledby="knowledge-tab-search" hidden={activeTab !== "search"} className="mt-6">
        <div className="flex items-center gap-2">
          <Search className="h-4 w-4 text-gray-600" />
          <h3 className="text-sm font-semibold">检索已发布知识</h3>
        </div>
        <form onSubmit={runSearch} className="mt-4 grid gap-3 sm:grid-cols-[minmax(0,1fr)_112px_auto] sm:items-end">
          <div>
            <label className="mb-1.5 block text-sm font-medium text-gray-700" htmlFor="knowledge-search-query">检索内容</label>
            <input id="knowledge-search-query" type="search" value={searchQuery} onChange={(event) => setSearchQuery(event.target.value)} maxLength={500} placeholder="输入方法论、规则、基准或 SOP" className="h-10 w-full rounded-md border border-gray-300 px-3 text-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100" />
          </div>
          <div>
            <label className="mb-1.5 block text-sm font-medium text-gray-700" htmlFor="knowledge-search-limit">结果条数</label>
            <input id="knowledge-search-limit" type="number" min={1} max={100} value={searchLimit} onChange={(event) => setSearchLimit(Number(event.target.value))} onBlur={() => setSearchLimit(Math.min(100, Math.max(1, Math.trunc(searchLimit || 10))))} className="h-10 w-full rounded-md border border-gray-300 px-3 text-sm tabular-nums outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100" />
          </div>
          <button type="submit" disabled={searchLoading || !searchQuery.trim()} className="flex h-10 items-center justify-center gap-2 rounded-md bg-gray-900 px-4 text-sm font-medium text-white hover:bg-gray-800 disabled:cursor-not-allowed disabled:opacity-50">
            {searchLoading ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
            <span>{searchLoading ? "检索中..." : "检索"}</span>
          </button>
        </form>

        {searchError && <div role="alert" className="mt-4 border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{searchError}</div>}
        {searched && !searchLoading && !searchError && (
          <div className="mt-6">
            <p className="mb-3 text-xs text-gray-500">找到 {searchResults.length} 条相关内容</p>
            {searchResults.length === 0 ? (
              <div className="border border-gray-200 bg-white px-4 py-10 text-center text-sm text-gray-500">没有检索到相关知识</div>
            ) : (
              <ol className="divide-y divide-gray-200 border border-gray-200 bg-white">
                {searchResults.map((result) => (
                  <li key={result.chunk_id} className="px-4 py-5 sm:px-5">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-xs font-semibold tabular-nums text-gray-400">#{result.rank}</span>
                          <h4 className="text-sm font-semibold text-gray-900">{result.document_title}</h4>
                          <span className="rounded bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-600">v{result.version_no}</span>
                          <span className="rounded bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-700">{sourceTypeLabel(result.source_type)}</span>
                        </div>
                        {locatorLabel(result.locator) && <p className="mt-1 text-xs text-gray-400">{locatorLabel(result.locator)}</p>}
                      </div>
                      <a href={api.getKnowledgePreviewUrl(result.document_id, result.version_id)} target="_blank" rel="noreferrer" className="flex h-9 shrink-0 items-center gap-2 rounded-md border border-gray-300 px-3 text-xs font-medium text-gray-700 hover:bg-gray-50">
                        <ExternalLink className="h-3.5 w-3.5" />
                        查看预览
                      </a>
                    </div>
                    <p className="mt-3 line-clamp-4 whitespace-pre-wrap break-words text-sm leading-6 text-gray-700">{result.quote}</p>
                    <div className="mt-4 grid grid-cols-2 border-y border-gray-100 sm:grid-cols-4">
                      <ScoreMetric label="综合相关度" value={result.combined_score_percent} />
                      <ScoreMetric label="语义相关度" value={result.semantic_score_percent} />
                      <ScoreMetric label="关键词命中率" value={result.keyword_match_percent} />
                      <ScoreMetric label="资料类型权重" value={result.source_weight_percent} prefix="+" />
                    </div>
                  </li>
                ))}
              </ol>
            )}
          </div>
        )}
      </div>

      <div id="knowledge-panel-sync" role="tabpanel" aria-labelledby="knowledge-tab-sync" hidden={activeTab !== "sync"} className="mt-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <Database className="h-4 w-4 text-gray-600" />
              <h3 className="text-sm font-semibold">内置行业文档同步</h3>
            </div>
            <p className="mt-1 text-xs text-gray-500">自动同步 100 个子行业文档；未变化文件跳过，目录删除会撤回已发布版本。</p>
          </div>
          <div className="flex items-center gap-2">
            {syncRun && syncRun.failed_count > 0 && !isSyncActive(syncRun.state) && (
              <button type="button" onClick={() => void retryFailedSync()} disabled={syncAction !== null} className="flex h-9 items-center gap-2 rounded-md border border-gray-300 px-3 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50">
                {syncAction === "retry" ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <RotateCcw className="h-4 w-4" />}
                重试失败项
              </button>
            )}
            <button type="button" onClick={() => void startSync()} disabled={syncAction !== null || Boolean(syncRun && isSyncActive(syncRun.state))} className="flex h-9 items-center gap-2 rounded-md bg-gray-900 px-3 text-xs font-medium text-white hover:bg-gray-800 disabled:cursor-not-allowed disabled:opacity-50">
              {syncAction === "start" || (syncRun && isSyncActive(syncRun.state)) ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
              立即同步
            </button>
          </div>
        </div>

        {syncLoading ? (
          <div className="py-8 text-center text-sm text-gray-500">正在读取同步状态...</div>
        ) : syncRun ? (
          <div className="mt-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-2 text-sm">
                <SyncRunStatus run={syncRun} />
                <span className="text-xs text-gray-400">{triggerLabel(syncRun.trigger)} · {formatTime(syncRun.created_at)}</span>
              </div>
              <span className="text-sm font-semibold tabular-nums">{syncRun.progress_percent}%</span>
            </div>
            <div className="mt-2 h-2 overflow-hidden rounded bg-gray-100" aria-label={`同步进度 ${syncRun.progress_percent}%`}>
              <div className="h-full bg-emerald-600 transition-[width] duration-300" style={{ width: `${syncRun.progress_percent}%` }} />
            </div>
            <div className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-3 lg:grid-cols-6">
              <SyncCount label="待处理" value={syncRun.pending_count} />
              <SyncCount label="处理中" value={syncRun.processing_count} />
              <SyncCount label="已发布" value={syncRun.published_count} />
              <SyncCount label="已跳过" value={syncRun.skipped_count} />
              <SyncCount label="已撤回" value={syncRun.revoked_count} />
              <SyncCount label="失败" value={syncRun.failed_count} danger={syncRun.failed_count > 0} />
            </div>
            {syncRun.error && <p className="mt-4 flex items-start gap-2 text-xs text-amber-700"><AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />{syncRun.error}</p>}
            {syncRun.items.length > 0 && (
              <div className="mt-5 max-h-80 overflow-y-auto border border-gray-200 bg-white">
                <ul className="divide-y divide-gray-100">
                  {syncRun.items.map((item) => <SyncItemRow key={item.id} item={item} />)}
                </ul>
              </div>
            )}
          </div>
        ) : (
          <div className="py-8 text-center text-sm text-gray-500">尚未执行行业文档同步</div>
        )}
      </div>

      <div id="knowledge-panel-versions" role="tabpanel" aria-labelledby="knowledge-tab-versions" hidden={activeTab !== "versions"} className="mt-6">
        <div className="mb-4 flex items-center justify-between gap-4">
          <div><h3 className="text-base font-semibold text-slate-900">资料版本</h3><p className="mt-1 text-sm text-slate-500">共 {total} 个版本</p></div>
          <button onClick={() => void loadVersions()} disabled={loading} title="刷新资料版本" aria-label="刷新资料版本" className="flex h-9 w-9 items-center justify-center rounded-md border border-slate-200 text-slate-500 transition hover:border-slate-300 hover:bg-slate-50 disabled:opacity-50"><RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} /></button>
        </div>
        <div className="overflow-hidden border border-slate-200 bg-white shadow-sm">
          <div className="overflow-x-auto">
            <table className="min-w-full border-collapse text-left">
              <thead className="bg-slate-50">
                <tr className="border-b border-slate-200 text-xs font-semibold text-slate-500">
                  <th className="w-[34%] px-5 py-3">资料名称</th>
                  <th className="w-[22%] px-5 py-3">版本</th>
                  <th className="w-[16%] px-5 py-3">状态</th>
                  <th className="w-[18%] px-5 py-3">更新时间</th>
                  <th className="w-32 px-4 py-3 text-right"><span className="sr-only">操作</span></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {loading ? <tr><td colSpan={5} className="px-5 py-14 text-center text-sm text-slate-500">正在加载...</td></tr> : versions.length === 0 ? <tr><td colSpan={5} className="px-5 py-14 text-center text-sm text-slate-500">暂无行业资料版本</td></tr> : (
                  versions.map((item) => <tr key={item.version.id} className="transition hover:bg-slate-50/70">
                    <td className="px-5 py-4"><div className="min-w-0"><p className="truncate text-sm font-medium text-slate-900">{item.document_title}</p><p className="mt-1 truncate text-xs text-slate-400">{item.version.original_filename}</p></div></td>
                    <td className="px-5 py-4"><div className="flex items-center gap-2"><span className="text-sm font-medium text-slate-800">v{item.version.version_no}</span><span className="text-xs text-slate-500">{sourceTypeLabel(item.version.source_type)}</span>{item.is_current && <span className="rounded bg-blue-50 px-1.5 py-0.5 text-xs font-medium text-blue-700">当前</span>}</div></td>
                    <td className="px-5 py-4"><VersionStatus status={item.version.status} /></td>
                    <td className="px-5 py-4 text-sm tabular-nums text-slate-500">{formatTime(item.version.updated_at)}</td>
                    <td className="px-4 py-4 text-right"><VersionActions item={item} processing={processingVersion === item.version.id} onProcess={process} onReplace={startReplacement} /></td>
                  </tr>)
                )}
              </tbody>
            </table>
          </div>
          <Pagination
            page={page}
            pageSize={pageSize}
            total={total}
            disabled={loading}
            onPageChange={setPage}
            onPageSizeChange={(size) => {
              setPage(1);
              setPageSize(size);
            }}
          />
        </div>
      </div>
    </section>
  );
}

function TextInput({ label, value, onChange, placeholder }: { label: string; value: string; onChange: (value: string) => void; placeholder: string }) {
  const id = `knowledge-${label}`;
  return <div><label className="mb-1.5 block text-sm font-medium text-gray-700" htmlFor={id}>{label}</label><input id={id} value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} className="h-10 w-full rounded-md border border-gray-300 px-3 text-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100" /></div>;
}

function ScoreMetric({ label, value, prefix = "" }: { label: string; value: number; prefix?: string }) {
  return <div className="px-2 py-3 first:pl-0 sm:px-3"><p className="text-xs text-gray-400">{label}</p><p className="mt-1 text-sm font-semibold tabular-nums text-gray-800">{prefix}{formatPercent(value)}</p></div>;
}

function formatPercent(value: number): string {
  return `${Number.isInteger(value) ? value.toFixed(0) : value.toFixed(1)}%`;
}

function locatorLabel(locator: Record<string, unknown>): string {
  const parts: string[] = [];
  if (Array.isArray(locator.heading_path)) {
    const headings = locator.heading_path.filter((item): item is string => typeof item === "string" && Boolean(item));
    if (headings.length > 0) parts.push(headings.join(" / "));
  }
  if (typeof locator.line_start === "number") {
    const end = typeof locator.line_end === "number" ? locator.line_end : locator.line_start;
    parts.push(locator.line_start === end ? `第 ${locator.line_start} 行` : `第 ${locator.line_start}–${end} 行`);
  } else if (typeof locator.paragraph_start === "number") {
    const end = typeof locator.paragraph_end === "number" ? locator.paragraph_end : locator.paragraph_start;
    parts.push(locator.paragraph_start === end ? `第 ${locator.paragraph_start} 段` : `第 ${locator.paragraph_start}–${end} 段`);
  } else if (typeof locator.table_no === "number") {
    parts.push(`表格 ${locator.table_no}`);
  }
  return parts.join(" · ");
}

function isSyncActive(state: KnowledgeCatalogSyncRun["state"]): boolean {
  return state === "queued" || state === "scanning" || state === "running";
}

function triggerLabel(trigger: KnowledgeCatalogSyncRun["trigger"]): string {
  return { startup: "启动同步", manual: "手动同步", retry: "失败重试" }[trigger];
}

function formatTime(value: string): string {
  return formatAppDateTime(value, { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function SyncRunStatus({ run }: { run: KnowledgeCatalogSyncRun }) {
  const config: Record<KnowledgeCatalogSyncRun["state"], [string, string]> = {
    queued: ["等待执行", "bg-gray-100 text-gray-600"],
    scanning: ["正在扫描", "bg-amber-50 text-amber-700"],
    running: ["正在入库", "bg-blue-50 text-blue-700"],
    completed: ["同步完成", "bg-emerald-50 text-emerald-700"],
    partial_failed: ["部分失败", "bg-amber-50 text-amber-700"],
    failed: ["同步失败", "bg-red-50 text-red-700"],
  };
  const [label, className] = config[run.state];
  return <span className={`rounded px-2 py-1 text-xs font-medium ${className}`}>{label}</span>;
}

function SyncCount({ label, value, danger = false }: { label: string; value: number; danger?: boolean }) {
  return <div><p className="text-xs text-gray-400">{label}</p><p className={`mt-0.5 text-sm font-semibold tabular-nums ${danger ? "text-red-600" : "text-gray-800"}`}>{value}</p></div>;
}

function SyncItemRow({ item }: { item: KnowledgeCatalogSyncItem }) {
  const status: Record<KnowledgeCatalogSyncItem["state"], [string, string]> = {
    queued: ["待处理", "text-gray-500"],
    running: ["处理中", "text-blue-600"],
    published: ["已发布", "text-emerald-700"],
    skipped: ["已跳过", "text-gray-500"],
    failed: ["失败", "text-red-600"],
    revoked: ["已撤回", "text-amber-700"],
  };
  const action = { scan: "校验", create: "新增", update: "更新", skip: "未变化", revoke: "目录删除" }[item.action];
  const [label, className] = status[item.state];
  return <li className="flex items-start justify-between gap-4 px-3 py-2.5">
    <div className="flex min-w-0 items-start gap-2">
      {item.state === "queued" || item.state === "running" ? <LoaderCircle className={`mt-0.5 h-3.5 w-3.5 shrink-0 ${item.state === "running" ? "animate-spin text-blue-600" : "text-gray-400"}`} /> : item.state === "failed" ? <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-red-600" /> : <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-600" />}
      <div className="min-w-0">
        <p className="truncate text-xs font-medium text-gray-800">{item.filename}</p>
        <p className="mt-0.5 text-xs text-gray-400">{action}{item.retry_count > 0 ? ` · 已重试 ${item.retry_count} 次` : ""}</p>
        {item.error && <p className="mt-1 break-words text-xs text-red-600">{item.error}</p>}
      </div>
    </div>
    <span className={`shrink-0 text-xs font-medium ${className}`}>{label}</span>
  </li>;
}

function VersionActions({ item, processing, onProcess, onReplace }: { item: KnowledgeDocumentVersionListItem; processing: boolean; onProcess: (version: KnowledgeVersion, action: "publish" | "revoke" | "retry") => Promise<void>; onReplace: (item: KnowledgeDocumentVersionListItem) => void }) {
  if (item.managed_source_key) return null;
  const { version } = item;
  return <div className="inline-flex items-center gap-1">
    <ActionButton title="上传新版本" disabled={processing} onClick={() => onReplace(item)}><FileUp className="h-3.5 w-3.5" /></ActionButton>
    {version.status === "pending_review" && <ActionButton title="发布版本" disabled={processing} onClick={() => void onProcess(version, "publish")}><Send className="h-3.5 w-3.5" /></ActionButton>}
    {version.status === "draft" && version.latest_job?.state === "failed" && <ActionButton title="重新解析" disabled={processing} onClick={() => void onProcess(version, "retry")}><RotateCcw className="h-3.5 w-3.5" /></ActionButton>}
    {version.status !== "revoked" && <ActionButton title="撤回版本" disabled={processing} danger onClick={() => void onProcess(version, "revoke")}><X className="h-3.5 w-3.5" /></ActionButton>}
  </div>;
}

function ActionButton({ title, disabled, danger, onClick, children }: { title: string; disabled: boolean; danger?: boolean; onClick: () => void; children: ReactNode }) {
  return <button type="button" title={title} aria-label={title} disabled={disabled} onClick={onClick} className={`flex h-8 w-8 items-center justify-center rounded-md disabled:opacity-40 ${danger ? "text-red-600 hover:bg-red-50" : "text-blue-600 hover:bg-blue-50"}`}>{children}</button>;
}

function VersionStatus({ status }: { status: KnowledgeVersion["status"] }) {
  const config = {
    draft: ["草稿", "bg-gray-100 text-gray-600"], parsing: ["解析中", "bg-amber-50 text-amber-700"], indexing: ["索引中", "bg-amber-50 text-amber-700"], pending_review: ["待审核", "bg-blue-50 text-blue-700"], published: ["已发布", "bg-emerald-50 text-emerald-700"], superseded: ["已替代", "bg-gray-100 text-gray-600"], revoked: ["已撤回", "bg-red-50 text-red-700"],
  }[status];
  return <span className={`rounded px-2 py-0.5 text-xs font-medium ${config[1]}`}>{config[0]}</span>;
}

function sourceTypeLabel(type: KnowledgeSourceType): string { return SOURCE_TYPES.find((item) => item.value === type)?.label ?? type; }
function readableError(error: unknown): string { if (!(error instanceof Error)) return "操作失败，请稍后重试"; const marker = error.message.indexOf(": "); return marker >= 0 ? error.message.slice(marker + 2) : error.message; }
