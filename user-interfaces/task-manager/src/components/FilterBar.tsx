import { Search, X, Filter } from 'lucide-react';
import { clsx } from 'clsx';
import type { FilterState } from '@/types';

interface FilterBarProps {
  filters: FilterState;
  onFilterChange: (filters: FilterState) => void;
  topics: string[];
  assignees: string[];
}

export function FilterBar({ filters, onFilterChange, topics, assignees }: FilterBarProps) {
  const hasActiveFilters = filters.status || filters.topic || filters.assignee || filters.priority || filters.search;

  const clearFilters = () => {
    onFilterChange({
      status: null,
      topic: null,
      assignee: null,
      priority: null,
      search: '',
    });
  };

  return (
    <div className="bg-white border-b border-gray-200 p-4">
      <div className="flex flex-wrap items-center gap-3">
        {/* Search */}
        <div className="relative flex-1 min-w-[200px] max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
          <input
            type="text"
            placeholder="Search tasks..."
            value={filters.search}
            onChange={(e) => onFilterChange({ ...filters, search: e.target.value })}
            className="w-full pl-10 pr-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
          />
          {filters.search && (
            <button
              onClick={() => onFilterChange({ ...filters, search: '' })}
              className="absolute right-3 top-1/2 -translate-y-1/2 p-0.5 hover:bg-gray-100 rounded"
            >
              <X className="w-4 h-4 text-gray-400" />
            </button>
          )}
        </div>

        {/* Status Filter */}
        <select
          value={filters.status || ''}
          onChange={(e) => onFilterChange({ ...filters, status: e.target.value || null })}
          className={clsx(
            'px-3 py-2 border rounded-lg bg-white focus:ring-2 focus:ring-primary-500 focus:border-primary-500',
            filters.status ? 'border-primary-500 text-primary-700' : 'border-gray-300'
          )}
        >
          <option value="">All Statuses</option>
          <option value="pending">Pending</option>
          <option value="in_progress">In Progress</option>
          <option value="completed">Completed</option>
        </select>

        {/* Topic Filter */}
        <select
          value={filters.topic || ''}
          onChange={(e) => onFilterChange({ ...filters, topic: e.target.value || null })}
          className={clsx(
            'px-3 py-2 border rounded-lg bg-white focus:ring-2 focus:ring-primary-500 focus:border-primary-500',
            filters.topic ? 'border-primary-500 text-primary-700' : 'border-gray-300'
          )}
        >
          <option value="">All Topics</option>
          {topics.sort().map((topic) => (
            <option key={topic} value={topic}>
              {topic}
            </option>
          ))}
        </select>

        {/* Assignee Filter */}
        <select
          value={filters.assignee || ''}
          onChange={(e) => onFilterChange({ ...filters, assignee: e.target.value || null })}
          className={clsx(
            'px-3 py-2 border rounded-lg bg-white focus:ring-2 focus:ring-primary-500 focus:border-primary-500',
            filters.assignee ? 'border-primary-500 text-primary-700' : 'border-gray-300'
          )}
        >
          <option value="">All Assignees</option>
          {assignees.sort().map((assignee) => (
            <option key={assignee} value={assignee}>
              {assignee}
            </option>
          ))}
        </select>

        {/* Priority Filter */}
        <select
          value={filters.priority || ''}
          onChange={(e) => onFilterChange({ ...filters, priority: e.target.value || null })}
          className={clsx(
            'px-3 py-2 border rounded-lg bg-white focus:ring-2 focus:ring-primary-500 focus:border-primary-500',
            filters.priority ? 'border-primary-500 text-primary-700' : 'border-gray-300'
          )}
        >
          <option value="">All Priorities</option>
          <option value="high">High</option>
          <option value="medium">Medium</option>
          <option value="low">Low</option>
        </select>

        {/* Clear Filters */}
        {hasActiveFilters && (
          <button
            onClick={clearFilters}
            className="flex items-center gap-1.5 px-3 py-2 text-sm text-gray-600 hover:text-gray-900 hover:bg-gray-100 rounded-lg transition-colors"
          >
            <X className="w-4 h-4" />
            Clear filters
          </button>
        )}
      </div>

      {/* Active Filter Tags */}
      {hasActiveFilters && (
        <div className="flex flex-wrap items-center gap-2 mt-3 pt-3 border-t border-gray-100">
          <Filter className="w-4 h-4 text-gray-400" />
          <span className="text-sm text-gray-500">Active filters:</span>

          {filters.search && (
            <span className="inline-flex items-center gap-1 px-2 py-1 bg-gray-100 text-gray-700 rounded text-sm">
              Search: "{filters.search}"
              <button
                onClick={() => onFilterChange({ ...filters, search: '' })}
                className="hover:text-gray-900"
              >
                <X className="w-3 h-3" />
              </button>
            </span>
          )}

          {filters.status && (
            <span className="inline-flex items-center gap-1 px-2 py-1 bg-purple-100 text-purple-700 rounded text-sm">
              Status: {filters.status === 'in_progress' ? 'In Progress' : filters.status.charAt(0).toUpperCase() + filters.status.slice(1)}
              <button
                onClick={() => onFilterChange({ ...filters, status: null })}
                className="hover:text-purple-900"
              >
                <X className="w-3 h-3" />
              </button>
            </span>
          )}

          {filters.topic && (
            <span className="inline-flex items-center gap-1 px-2 py-1 bg-primary-100 text-primary-700 rounded text-sm">
              Topic: {filters.topic}
              <button
                onClick={() => onFilterChange({ ...filters, topic: null })}
                className="hover:text-primary-900"
              >
                <X className="w-3 h-3" />
              </button>
            </span>
          )}

          {filters.assignee && (
            <span className="inline-flex items-center gap-1 px-2 py-1 bg-blue-100 text-blue-700 rounded text-sm">
              Assignee: {filters.assignee}
              <button
                onClick={() => onFilterChange({ ...filters, assignee: null })}
                className="hover:text-blue-900"
              >
                <X className="w-3 h-3" />
              </button>
            </span>
          )}

          {filters.priority && (
            <span className="inline-flex items-center gap-1 px-2 py-1 bg-orange-100 text-orange-700 rounded text-sm">
              Priority: {filters.priority}
              <button
                onClick={() => onFilterChange({ ...filters, priority: null })}
                className="hover:text-orange-900"
              >
                <X className="w-3 h-3" />
              </button>
            </span>
          )}
        </div>
      )}
    </div>
  );
}
