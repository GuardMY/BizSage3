"use client";

import { FormEvent, type ReactNode, useCallback, useEffect, useState } from "react";
import { BookOpen, FileUp, LoaderCircle, RefreshCw, RotateCcw, Send, X } from "lucide-react";
import * as api from "@/lib/api";
import type { KnowledgeDocument, KnowledgeSourceType, KnowledgeVersion } from "@/types";

const SOURCE_TYPES: Array<{ value: KnowledgeSourceType; label: string }> = [
  { value: "methodology", label: "行业方法论" },
  { value: "benchmark_rule", label: "基准与规则" },
  { value: "case_sop", label: "脱敏案例与 SOP" },
];

export default function KnowledgeManagement() {
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [processingVersion, setProcessingVersion] = useState<string | null>(null);
  const [replacementFor, setReplacementFor] = useState<KnowledgeDocument | null>(null);
  const [title, setTitle] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [sourceType, setSourceType] = useState<KnowledgeSourceType>("methodology");
  const [industryTags, setIndustryTags] = useState("");
  const [subIndustryTags, setSubIndustryTags] = useState("");
  const [businessModeTags, setBusinessModeTags] = useState("");
  const [operatingStageTags, setOperatingStageTags] = useState("");
  const [error, setError] = useState<string | null>(null);

  const loadDocuments = useCallback(async () => {
    setLoading(true);
    try {
      setDocuments(await api.listKnowledgeDocuments());
    } catch (err) {
      setError(readableError(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void loadDocuments(); }, [loadDocuments]);

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

  function startReplacement(document: KnowledgeDocument) {
    setReplacementFor(document);
    setTitle(document.title);
    const current = document.versions.find((item) => item.id === document.current_version_id) ?? document.versions[0];
    if (current) {
      setSourceType(current.source_type);
      setIndustryTags(current.industry_tags.join(", "));
      setSubIndustryTags(current.sub_industry_tags.join(", "));
      setBusinessModeTags(current.business_mode_tags.join(", "));
      setOperatingStageTags(current.operating_stage_tags.join(", "));
    }
    setFile(null);
    setError(null);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!file || submitting || (!replacementFor && !title.trim())) return;
    setSubmitting(true);
    setError(null);
    const payload = { title, sourceType, file, industryTags, subIndustryTags, businessModeTags, operatingStageTags };
    try {
      if (replacementFor) await api.createKnowledgeDocumentVersion(replacementFor.id, payload);
      else await api.createKnowledgeDocument(payload);
      resetForm();
      await loadDocuments();
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
      await loadDocuments();
    } catch (err) {
      setError(readableError(err));
    } finally {
      setProcessingVersion(null);
    }
  }

  return (
    <section className="mt-12 border-t border-gray-200 pt-8">
      <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_390px]">
        <div>
          <div className="flex items-center gap-2">
            <BookOpen className="h-5 w-5 text-indigo-600" />
            <h2 className="text-sm font-semibold">行业知识库</h2>
          </div>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-gray-500">
            已发布版本才会参与诊断检索。替代或撤回不会改写历史报告；撤回后来源详情和原件立即不可访问。
          </p>
        </div>
        <form onSubmit={submit} className="space-y-3 rounded-md border border-gray-200 bg-white p-5 shadow-sm">
          <div className="flex items-center justify-between gap-3">
            <h3 className="text-sm font-semibold">{replacementFor ? `上传 ${replacementFor.title} 的新版本` : "上传资料"}</h3>
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

      {error && <div role="alert" className="mt-6 border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}

      <div className="mt-8">
        <div className="mb-4 flex items-center justify-between gap-4">
          <div><h3 className="text-sm font-semibold">资料版本</h3><p className="mt-1 text-xs text-gray-500">共 {documents.length} 份资料</p></div>
          <button onClick={() => void loadDocuments()} disabled={loading} title="刷新资料列表" aria-label="刷新资料列表" className="flex h-9 w-9 items-center justify-center rounded-md text-gray-500 hover:bg-gray-100 disabled:opacity-50"><RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} /></button>
        </div>
        <div className="overflow-hidden rounded-md border border-gray-200 bg-white">
          {loading ? <div className="px-4 py-12 text-center text-sm text-gray-500">正在加载...</div> : documents.length === 0 ? <div className="px-4 py-12 text-center text-sm text-gray-500">暂无行业资料</div> : (
            <ul className="divide-y divide-gray-100">
              {documents.map((document) => <li key={document.id} className="px-4 py-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0"><p className="truncate text-sm font-medium text-gray-900">{document.title}</p><p className="mt-1 text-xs text-gray-400">{document.versions.length} 个版本</p></div>
                  <button onClick={() => startReplacement(document)} className="flex h-8 items-center gap-1.5 rounded-md border border-gray-300 px-2.5 text-xs font-medium text-gray-700 hover:bg-gray-50"><FileUp className="h-3.5 w-3.5" /> 新版本</button>
                </div>
                <ul className="mt-3 divide-y divide-gray-100 border-t border-gray-100">
                  {document.versions.map((version) => <VersionRow key={version.id} version={version} processing={processingVersion === version.id} onProcess={process} />)}
                </ul>
              </li>)}
            </ul>
          )}
        </div>
      </div>
    </section>
  );
}

function TextInput({ label, value, onChange, placeholder }: { label: string; value: string; onChange: (value: string) => void; placeholder: string }) {
  const id = `knowledge-${label}`;
  return <div><label className="mb-1.5 block text-sm font-medium text-gray-700" htmlFor={id}>{label}</label><input id={id} value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} className="h-10 w-full rounded-md border border-gray-300 px-3 text-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100" /></div>;
}

function VersionRow({ version, processing, onProcess }: { version: KnowledgeVersion; processing: boolean; onProcess: (version: KnowledgeVersion, action: "publish" | "revoke" | "retry") => Promise<void> }) {
  const tagSummary = [version.industry_tags, version.business_mode_tags, version.operating_stage_tags].flat().join(" · ");
  return <li className="flex flex-wrap items-center justify-between gap-3 py-3 first:pt-3">
    <div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><span className="text-sm font-medium text-gray-800">v{version.version_no}</span><VersionStatus status={version.status} /></div><p className="mt-1 truncate text-xs text-gray-500">{version.original_filename} · {sourceTypeLabel(version.source_type)} · {version.chunk_count} 个切片{tagSummary ? ` · ${tagSummary}` : ""}</p>{version.latest_job?.error && <p className="mt-1 text-xs text-red-600">解析失败：{version.latest_job.error}</p>}</div>
    <div className="flex shrink-0 items-center gap-1">
      {version.status === "pending_review" && <ActionButton title="发布版本" disabled={processing} onClick={() => void onProcess(version, "publish")}><Send className="h-3.5 w-3.5" /></ActionButton>}
      {version.status === "draft" && version.latest_job?.state === "failed" && <ActionButton title="重新解析" disabled={processing} onClick={() => void onProcess(version, "retry")}><RotateCcw className="h-3.5 w-3.5" /></ActionButton>}
      {version.status !== "revoked" && <ActionButton title="撤回版本" disabled={processing} danger onClick={() => void onProcess(version, "revoke")}><X className="h-3.5 w-3.5" /></ActionButton>}
    </div>
  </li>;
}

function ActionButton({ title, disabled, danger, onClick, children }: { title: string; disabled: boolean; danger?: boolean; onClick: () => void; children: ReactNode }) {
  return <button type="button" title={title} aria-label={title} disabled={disabled} onClick={onClick} className={`flex h-8 w-8 items-center justify-center rounded-md disabled:opacity-40 ${danger ? "text-red-600 hover:bg-red-50" : "text-indigo-600 hover:bg-indigo-50"}`}>{children}</button>;
}

function VersionStatus({ status }: { status: KnowledgeVersion["status"] }) {
  const config = {
    draft: ["草稿", "bg-gray-100 text-gray-600"], parsing: ["解析中", "bg-amber-50 text-amber-700"], pending_review: ["待审核", "bg-blue-50 text-blue-700"], published: ["已发布", "bg-emerald-50 text-emerald-700"], superseded: ["已替代", "bg-gray-100 text-gray-600"], revoked: ["已撤回", "bg-red-50 text-red-700"],
  }[status];
  return <span className={`rounded px-2 py-0.5 text-xs font-medium ${config[1]}`}>{config[0]}</span>;
}

function sourceTypeLabel(type: KnowledgeSourceType): string { return SOURCE_TYPES.find((item) => item.value === type)?.label ?? type; }
function readableError(error: unknown): string { if (!(error instanceof Error)) return "操作失败，请稍后重试"; const marker = error.message.indexOf(": "); return marker >= 0 ? error.message.slice(marker + 2) : error.message; }
