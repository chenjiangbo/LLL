'use client';

import React, { useState, useRef } from 'react';
import { X, Upload, FileText, Loader2, Calendar, CheckCircle2, AlertCircle } from 'lucide-react';

interface ImportModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: (tradeDate: string) => void;
  apiBase?: string;
}

export default function ImportModal({ isOpen, onClose, onSuccess, apiBase = 'http://127.0.0.1:18080' }: ImportModalProps) {
  const [tradeDate, setTradeDate] = useState('');
  const [content, setContent] = useState('');
  const [fileName, setFileName] = useState<string | null>(null);
  const [dateSource, setDateSource] = useState<'filename' | 'content' | 'manual' | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);

  if (!isOpen) return null;

  const extractDateFromText = (text: string): string | null => {
    if (!text) return null;
    // 1. 匹配 8 位纯数字格式，如 20260813
    const match8 = text.match(/20\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])/);
    if (match8) {
      const raw = match8[0];
      return `${raw.slice(0, 4)}-${raw.slice(4, 6)}-${raw.slice(6, 8)}`;
    }
    // 2. 匹配带分隔符格式，如 2026-08-13, 2026_08_13, 2026年8月13日
    const matchSep = text.match(/20\d{2}[-_年/.]?\d{1,2}[-_月/.]?\d{1,2}/);
    if (matchSep) {
      let d = matchSep[0].replace(/[年月.]/g, '-').replace(/日/, '').replace(/_/g, '-');
      const parts = d.split('-').filter(Boolean);
      if (parts.length === 3) {
        const year = parts[0];
        const month = parts[1].padStart(2, '0');
        const day = parts[2].padStart(2, '0');
        return `${year}-${month}-${day}`;
      }
    }
    return null;
  };

  const processFile = (file: File) => {
    setError(null);
    setFileName(file.name);

    const reader = new FileReader();
    reader.onload = (e) => {
      const text = e.target?.result as string;
      if (!text) {
        setError('文件内容为空');
        return;
      }
      setContent(text);

      // 1. 优先从文件名中匹配日期
      const filenameDate = extractDateFromText(file.name);
      if (filenameDate) {
        setTradeDate(filenameDate);
        setDateSource('filename');
        return;
      }

      // 2. 文件名无日期时，扫描文本内容前几行
      const contentDate = extractDateFromText(text.slice(0, 500));
      if (contentDate) {
        setTradeDate(contentDate);
        setDateSource('content');
        return;
      }

      // 3. 均无日期时，需人工选择
      setDateSource('manual');
      if (!tradeDate) {
        const today = new Date().toISOString().split('T')[0];
        setTradeDate(today);
      }
    };
    reader.readAsText(file);
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) processFile(file);
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    const file = e.dataTransfer.files?.[0];
    if (file) processFile(file);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!content.trim()) {
      setError('请上传或粘贴复盘文章 Markdown 内容');
      return;
    }
    if (!tradeDate.trim()) {
      setError('请输入或选择复盘交易日期');
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const res = await fetch(`${apiBase}/api/market-review/import`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          trade_date: tradeDate.trim(),
          content: content.trim(),
        }),
      });

      if (!res.ok) {
        const errText = await res.text();
        throw new Error(errText || `HTTP ${res.status}`);
      }

      const data = await res.json();
      const savedDate = data.trade_date || tradeDate;
      setLoading(false);
      onSuccess(savedDate);
      onClose();
    } catch (err) {
      setLoading(false);
      setError(err instanceof Error ? err.message : '复盘文章导入失败');
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-xs p-4">
      <div className="w-full max-w-2xl rounded-xl border border-[#c4c8bc]/40 bg-[#faf6f0] p-6 shadow-2xl space-y-4">
        {/* 顶部标题区 */}
        <div className="flex items-center justify-between border-b border-[#c4c8bc]/30 pb-3">
          <div className="flex items-center gap-2.5">
            <div className="rounded-lg bg-[#4a7c59]/10 p-2 text-[#4a7c59]">
              <FileText className="h-5 w-5" />
            </div>
            <div>
              <h2 className="text-lg font-bold text-[#2e3230]">导入复盘 Markdown 文件</h2>
              <p className="text-xs text-[#686d68]">拖拽或选择本地复盘文件，系统将自动识别日期并完成排版渲染</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="rounded-md p-1.5 text-[#686d68] hover:bg-[#e4e0d8] hover:text-[#2e3230]"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          {/* 1. 文件拖拽上传核心区域 (Dropzone) */}
          <div
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
            className={`cursor-pointer rounded-xl border-2 border-dashed p-6 text-center transition-all ${
              isDragging
                ? 'border-[#4a7c59] bg-[#4a7c59]/10 scale-[1.01]'
                : fileName
                ? 'border-[#4a7c59]/60 bg-white'
                : 'border-[#c4c8bc] bg-white/70 hover:border-[#4a7c59]/60 hover:bg-white'
            }`}
          >
            <input
              ref={fileInputRef}
              type="file"
              accept=".md,.txt"
              onChange={handleFileSelect}
              className="hidden"
            />
            <div className="flex flex-col items-center justify-center space-y-2">
              <div className="rounded-full bg-[#4a7c59]/10 p-3 text-[#4a7c59]">
                <Upload className="h-6 w-6" />
              </div>
              {fileName ? (
                <div>
                  <p className="text-sm font-bold text-[#2e3230]">{fileName}</p>
                  <p className="text-xs text-[#4a7c59] font-medium mt-0.5">点击或拖拽重新选择文件</p>
                </div>
              ) : (
                <div>
                  <p className="text-sm font-bold text-[#2e3230]">点击浏览选择，或拖拽 .md/.txt 复盘文件至此处</p>
                  <p className="text-xs text-[#686d68] mt-1">系统将自动从文件名或文中识别复盘交易日期</p>
                </div>
              )}
            </div>
          </div>

          {/* 2. 日期状态与选择行 */}
          <div className="rounded-lg border border-[#c4c8bc]/40 bg-white p-3 space-y-2">
            <div className="flex items-center justify-between gap-3">
              <label className="flex items-center gap-1.5 text-xs font-bold text-[#4a4e4a] shrink-0">
                <Calendar className="h-4 w-4 text-[#705c30]" />
                复盘交易日期：
              </label>

              {/* 日期选择器 input type="date" */}
              <input
                type="date"
                value={tradeDate}
                onChange={(e) => {
                  setTradeDate(e.target.value);
                  setDateSource('manual');
                }}
                className="rounded-md border border-[#c4c8bc]/60 bg-[#faf6f0] px-3 py-1.5 text-xs font-bold text-[#2e3230] outline-none focus:border-[#4a7c59]"
              />
            </div>

            {/* 日期来源反馈提示 */}
            {dateSource === 'filename' && (
              <div className="flex items-center gap-1.5 text-xs font-medium text-[#4a7c59] bg-[#4a7c59]/10 px-2.5 py-1 rounded">
                <CheckCircle2 className="h-3.5 w-3.5" />
                已成功从文件名中识别日期：<strong>{tradeDate}</strong>
              </div>
            )}
            {dateSource === 'content' && (
              <div className="flex items-center gap-1.5 text-xs font-medium text-[#705c30] bg-[#705c30]/10 px-2.5 py-1 rounded">
                <CheckCircle2 className="h-3.5 w-3.5" />
                文件名无日期，已从文章正文提取日期：<strong>{tradeDate}</strong>
              </div>
            )}
            {dateSource === 'manual' && (
              <div className="flex items-center gap-1.5 text-xs font-medium text-[#686d68] bg-[#f0ece4] px-2.5 py-1 rounded">
                <AlertCircle className="h-3.5 w-3.5 text-[#705c30]" />
                请核对复盘日期（如需修改可点击右侧日期选择框）
              </div>
            )}
          </div>

          {/* 3. 文章预览/编辑区 */}
          <div>
            <label className="mb-1 block text-xs font-bold text-[#4a4e4a]">文章内容预览与补充：</label>
            <textarea
              rows={6}
              value={content}
              onChange={(e) => setContent(e.target.value)}
              placeholder="文件内容将在此自动加载，也可在此直接复制粘贴 Markdown 复盘文章..."
              className="w-full rounded-md border border-[#c4c8bc]/60 bg-white p-3 font-mono text-xs leading-relaxed text-[#2e3230] outline-none focus:border-[#4a7c59]"
            />
          </div>

          {error && (
            <div className="rounded-md border border-[#b83230]/30 bg-[#b83230]/5 p-3 text-xs text-[#8f2927]">
              {error}
            </div>
          )}

          {/* 4. 底部操作按钮 */}
          <div className="flex items-center justify-end gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-md border border-[#c4c8bc]/60 bg-white px-4 py-2 text-xs font-bold text-[#4a4e4a] hover:bg-[#eae6de]"
            >
              取消
            </button>
            <button
              type="submit"
              disabled={loading || !content.trim()}
              className="inline-flex items-center gap-1.5 rounded-md bg-[#4a7c59] px-5 py-2 text-xs font-bold text-white shadow-xs hover:bg-[#3b6447] disabled:cursor-not-allowed disabled:opacity-60 transition-all"
            >
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileText className="h-4 w-4" />}
              {loading ? '正在保存导入...' : '确认导入复盘文章'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
