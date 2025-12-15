import { useState, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { RefreshCw, Plus } from 'lucide-react';
import { FilterBar, TaskList } from '@/components';
import { useTasks, useStats } from '@/hooks/useTasks';
import type { FilterState } from '@/types';

export function Tasks() {
  const [searchParams, setSearchParams] = useSearchParams();
  const { data: stats } = useStats();

  const [filters, setFilters] = useState<FilterState>({
    status: searchParams.get('status'),
    topic: searchParams.get('topic'),
    assignee: searchParams.get('assignee'),
    priority: searchParams.get('priority'),
    search: searchParams.get('search') || searchParams.get('q') || '',
  });

  const { data, isLoading, error, refetch, isFetching } = useTasks(filters);

  const handleFilterChange = (newFilters: FilterState) => {
    setFilters(newFilters);

    // Update URL params
    const params = new URLSearchParams();
    if (newFilters.status) params.set('status', newFilters.status);
    if (newFilters.topic) params.set('topic', newFilters.topic);
    if (newFilters.assignee) params.set('assignee', newFilters.assignee);
    if (newFilters.priority) params.set('priority', newFilters.priority);
    if (newFilters.search) params.set('q', newFilters.search);
    setSearchParams(params);
  };

  const topics = useMemo(() => stats?.topics || [], [stats]);
  const assignees = useMemo(() => stats?.assignees || [], [stats]);

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="bg-white border-b border-gray-200 px-6 py-4">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold text-gray-900">All Tasks</h1>
            <p className="text-sm text-gray-500 mt-0.5">
              {data ? (
                <>
                  Showing {data.count} of {data.total} tasks
                </>
              ) : (
                'Loading tasks...'
              )}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => refetch()}
              disabled={isFetching}
              className="flex items-center gap-2 px-3 py-2 text-sm bg-white border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-50 transition-colors"
            >
              <RefreshCw className={`w-4 h-4 ${isFetching ? 'animate-spin' : ''}`} />
              Refresh
            </button>
            <button
              className="flex items-center gap-2 px-3 py-2 text-sm bg-primary-600 text-white rounded-lg hover:bg-primary-700 transition-colors"
            >
              <Plus className="w-4 h-4" />
              New Task
            </button>
          </div>
        </div>
      </div>

      {/* Filter Bar */}
      <FilterBar
        filters={filters}
        onFilterChange={handleFilterChange}
        topics={topics}
        assignees={assignees}
      />

      {/* Task List */}
      <div className="flex-1 overflow-y-auto p-6">
        {error ? (
          <div className="bg-red-50 border border-red-200 rounded-lg p-4">
            <p className="text-red-800">Failed to load tasks. Please try again.</p>
          </div>
        ) : (
          <TaskList
            tasks={data?.tasks || []}
            isLoading={isLoading}
          />
        )}
      </div>
    </div>
  );
}
