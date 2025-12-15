import { useState, useMemo } from 'react';
import { User, Users, ChevronRight } from 'lucide-react';
import { clsx } from 'clsx';
import { TaskList } from '@/components';
import { useTasks } from '@/hooks/useTasks';
import type { Task } from '@/types';

interface AssigneeStats {
  name: string;
  tasks: Task[];
  high: number;
  medium: number;
  low: number;
  pending: number;
  completed: number;
}

export function Assignees() {
  const [selectedAssignee, setSelectedAssignee] = useState<string | null>(null);

  // Fetch all tasks for assignee stats
  const { data: allTasksData, isLoading: allLoading, error } = useTasks({
    status: null,
    topic: null,
    assignee: null,
    priority: null,
    search: '',
  });

  // Fetch filtered tasks when assignee is selected
  const { data: filteredData, isLoading: filteredLoading } = useTasks({
    status: null,
    topic: null,
    assignee: selectedAssignee,
    priority: null,
    search: '',
  });

  const isLoading = allLoading || (selectedAssignee && filteredLoading);

  const assigneeStats = useMemo(() => {
    if (!allTasksData) return [];

    const stats = new Map<string, AssigneeStats>();

    for (const task of allTasksData.tasks) {
      const name = task.assignee || 'Unassigned';

      if (!stats.has(name)) {
        stats.set(name, {
          name,
          tasks: [],
          high: 0,
          medium: 0,
          low: 0,
          pending: 0,
          completed: 0,
        });
      }

      const stat = stats.get(name)!;
      stat.tasks.push(task);
      stat[task.priority]++;
      if (task.status === 'completed') {
        stat.completed++;
      } else {
        stat.pending++;
      }
    }

    return Array.from(stats.values()).sort((a, b) => {
      // Unassigned goes last
      if (a.name === 'Unassigned') return 1;
      if (b.name === 'Unassigned') return -1;
      // Sort by task count descending
      return b.tasks.length - a.tasks.length;
    });
  }, [allTasksData]);

  const tasks = selectedAssignee
    ? (filteredData?.tasks || [])
    : (allTasksData?.tasks || []);

  if (error) {
    return (
      <div className="p-6">
        <div className="bg-red-50 border border-red-200 rounded-lg p-4">
          <p className="text-red-800">Failed to load assignees. Please try again.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="bg-white border-b border-gray-200 px-6 py-4">
        <h1 className="text-xl font-bold text-gray-900">Assignees</h1>
        <p className="text-sm text-gray-500 mt-0.5">
          View tasks by team member
        </p>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-hidden flex">
        {/* Sidebar - Assignee List */}
        <div className="w-80 border-r border-gray-200 overflow-y-auto bg-gray-50">
          {isLoading ? (
            <div className="p-4 animate-pulse space-y-2">
              {[1, 2, 3, 4].map(i => (
                <div key={i} className="h-16 bg-gray-200 rounded-lg" />
              ))}
            </div>
          ) : (
            <div className="p-2">
              {/* All Assignees option */}
              <button
                onClick={() => setSelectedAssignee(null)}
                className={clsx(
                  'w-full flex items-center gap-3 p-3 rounded-lg transition-colors text-left mb-2',
                  !selectedAssignee
                    ? 'bg-primary-100 text-primary-900'
                    : 'hover:bg-gray-100'
                )}
              >
                <div className="p-2 bg-primary-500 rounded-full">
                  <Users className="w-5 h-5 text-white" />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="font-medium text-gray-900">All Assignees</p>
                  <p className="text-sm text-gray-500">
                    {allTasksData?.tasks.length || 0} tasks total
                  </p>
                </div>
              </button>

              <div className="border-t border-gray-200 pt-2 mt-2">
                {assigneeStats.map((assignee) => (
                  <button
                    key={assignee.name}
                    onClick={() => setSelectedAssignee(assignee.name)}
                    className={clsx(
                      'w-full flex items-center gap-3 p-3 rounded-lg transition-colors text-left',
                      selectedAssignee === assignee.name
                        ? 'bg-primary-100 text-primary-900'
                        : 'hover:bg-gray-100'
                    )}
                  >
                    <div className={clsx(
                      'p-2 rounded-full',
                      assignee.name === 'Unassigned' ? 'bg-gray-300' : 'bg-blue-500'
                    )}>
                      <User className="w-5 h-5 text-white" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className={clsx(
                        'font-medium',
                        assignee.name === 'Unassigned' ? 'text-gray-500 italic' : 'text-gray-900'
                      )}>
                        {assignee.name}
                      </p>
                      <div className="flex items-center gap-2 text-xs mt-0.5">
                        <span className="text-gray-500">{assignee.tasks.length} tasks</span>
                        {assignee.high > 0 && (
                          <span className="px-1.5 py-0.5 bg-red-100 text-red-700 rounded">
                            {assignee.high} high
                          </span>
                        )}
                      </div>
                    </div>
                    <ChevronRight className="w-4 h-4 text-gray-400 flex-shrink-0" />
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Main - Task List */}
        <div className="flex-1 overflow-y-auto p-6">
          <div className="mb-4">
            <h2 className="text-lg font-semibold text-gray-900">
              {selectedAssignee || 'All Assignees'}
            </h2>
            <p className="text-sm text-gray-500">
              {tasks.length} task{tasks.length !== 1 ? 's' : ''}
            </p>
          </div>

          <TaskList
            tasks={tasks}
            isLoading={!!isLoading}
          />
        </div>
      </div>
    </div>
  );
}
