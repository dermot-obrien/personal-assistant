import { useState } from 'react';
import { RefreshCw, Database, Cloud, CheckCircle, AlertCircle, Settings as SettingsIcon, Download } from 'lucide-react';
import { useImportTasks } from '@/hooks/useTasks';
import type { ImportResponse } from '@/types';

export function Settings() {
  const [apiBase, setApiBase] = useState(import.meta.env.VITE_API_BASE || '/api');
  const importMutation = useImportTasks();
  const [dryRunResult, setDryRunResult] = useState<ImportResponse | null>(null);
  const [replaceMode, setReplaceMode] = useState(false);

  const handleImport = async (dryRun: boolean) => {
    try {
      const result = await importMutation.mutateAsync({ dryRun, replace: replaceMode });
      if (dryRun) {
        setDryRunResult(result);
      }
    } catch (error) {
      console.error('Import failed:', error);
    }
  };

  return (
    <div className="p-6 max-w-4xl">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-gray-900">Settings</h1>
        <p className="text-gray-500 mt-1">Configure your task manager</p>
      </div>

      {/* API Configuration */}
      <div className="bg-white rounded-xl border border-gray-200 p-6 mb-6">
        <div className="flex items-center gap-3 mb-4">
          <div className="p-2 bg-primary-100 rounded-lg">
            <Cloud className="w-5 h-5 text-primary-600" />
          </div>
          <div>
            <h2 className="text-lg font-semibold text-gray-900">API Configuration</h2>
            <p className="text-sm text-gray-500">Configure the backend API connection</p>
          </div>
        </div>

        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              API Base URL
            </label>
            <input
              type="text"
              value={apiBase}
              onChange={(e) => setApiBase(e.target.value)}
              placeholder="https://your-api.cloudfunctions.net"
              className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
            />
            <p className="mt-1 text-sm text-gray-500">
              The base URL for the task consolidator API. Set VITE_API_BASE in your .env file.
            </p>
          </div>

          <div className="flex items-center gap-2 p-3 bg-yellow-50 border border-yellow-200 rounded-lg">
            <AlertCircle className="w-5 h-5 text-yellow-600 flex-shrink-0" />
            <p className="text-sm text-yellow-800">
              Currently using mock data for development. Set VITE_USE_MOCK=false to use the real API.
            </p>
          </div>
        </div>
      </div>

      {/* Data Management */}
      <div className="bg-white rounded-xl border border-gray-200 p-6 mb-6">
        <div className="flex items-center gap-3 mb-4">
          <div className="p-2 bg-green-100 rounded-lg">
            <Database className="w-5 h-5 text-green-600" />
          </div>
          <div>
            <h2 className="text-lg font-semibold text-gray-900">Data Management</h2>
            <p className="text-sm text-gray-500">Import and manage task data</p>
          </div>
        </div>

        <div className="space-y-4">
          <div className="p-4 bg-gray-50 rounded-lg">
            <h3 className="font-medium text-gray-900 mb-2">Import Tasks from GCS</h3>
            <p className="text-sm text-gray-600 mb-4">
              Import tasks from individual task files stored in Google Cloud Storage.
              This will sync any new tasks that were extracted from transcripts.
            </p>

            <div className="mb-4">
              <label className="flex items-center gap-2 text-sm text-gray-700">
                <input
                  type="checkbox"
                  checked={replaceMode}
                  onChange={(e) => setReplaceMode(e.target.checked)}
                  className="rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                />
                Replace existing tasks (update tasks with same ID)
              </label>
            </div>

            <div className="flex gap-3">
              <button
                onClick={() => handleImport(true)}
                disabled={importMutation.isPending}
                className="px-4 py-2 text-sm bg-white border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-50 transition-colors"
              >
                Dry Run (Preview)
              </button>
              <button
                onClick={() => handleImport(false)}
                disabled={importMutation.isPending}
                className="flex items-center gap-2 px-4 py-2 text-sm bg-primary-600 text-white rounded-lg hover:bg-primary-700 disabled:opacity-50 transition-colors"
              >
                {importMutation.isPending && (
                  <RefreshCw className="w-4 h-4 animate-spin" />
                )}
                <Download className="w-4 h-4" />
                Import Now
              </button>
            </div>

            {importMutation.isSuccess && !dryRunResult && (
              <div className="mt-4 p-3 bg-green-50 border border-green-200 rounded-lg flex items-center gap-2">
                <CheckCircle className="w-5 h-5 text-green-600" />
                <p className="text-sm text-green-800">Import completed successfully!</p>
              </div>
            )}

            {importMutation.isError && (
              <div className="mt-4 p-3 bg-red-50 border border-red-200 rounded-lg flex items-center gap-2">
                <AlertCircle className="w-5 h-5 text-red-600" />
                <p className="text-sm text-red-800">Import failed. Please try again.</p>
              </div>
            )}

            {dryRunResult && (
              <div className="mt-4 p-4 bg-blue-50 border border-blue-200 rounded-lg">
                <h4 className="font-medium text-blue-900 mb-2">Dry Run Results</h4>
                <div className="grid grid-cols-3 gap-4 mb-3">
                  <div className="text-center p-2 bg-white rounded">
                    <p className="text-2xl font-bold text-green-600">{dryRunResult.imported_count}</p>
                    <p className="text-xs text-gray-500">To Import</p>
                  </div>
                  <div className="text-center p-2 bg-white rounded">
                    <p className="text-2xl font-bold text-yellow-600">{dryRunResult.skipped_count}</p>
                    <p className="text-xs text-gray-500">Skipped</p>
                  </div>
                  <div className="text-center p-2 bg-white rounded">
                    <p className="text-2xl font-bold text-blue-600">{dryRunResult.replaced_count}</p>
                    <p className="text-xs text-gray-500">To Replace</p>
                  </div>
                </div>
                <button
                  onClick={() => setDryRunResult(null)}
                  className="text-sm text-blue-600 hover:text-blue-700"
                >
                  Dismiss
                </button>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* About */}
      <div className="bg-white rounded-xl border border-gray-200 p-6">
        <div className="flex items-center gap-3 mb-4">
          <div className="p-2 bg-gray-100 rounded-lg">
            <SettingsIcon className="w-5 h-5 text-gray-600" />
          </div>
          <div>
            <h2 className="text-lg font-semibold text-gray-900">About</h2>
            <p className="text-sm text-gray-500">Task Manager v1.0</p>
          </div>
        </div>

        <div className="text-sm text-gray-600 space-y-2">
          <p>
            This interface manages consolidated tasks extracted from transcripts using the
            task-consolidator cloud function.
          </p>
          <p>
            Tasks are automatically extracted from Otter.ai and Plaud transcripts using
            Gemini AI, then consolidated into a single queryable database.
          </p>
        </div>
      </div>
    </div>
  );
}
