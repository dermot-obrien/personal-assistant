import { useState } from 'react';
import { TaskCard } from './TaskCard';
import { TaskDetail } from './TaskDetail';
import { ListFilter, LayoutGrid } from 'lucide-react';
import { clsx } from 'clsx';
import type { Task, GroupBy, SortBy } from '@/types';

interface TaskListProps {
  tasks: Task[];
  isLoading?: boolean;
}

function groupTasks(tasks: Task[], groupBy: GroupBy): Map<string, Task[]> {
  const groups = new Map<string, Task[]>();

  if (groupBy === 'none') {
    groups.set('All Tasks', tasks);
    return groups;
  }

  for (const task of tasks) {
    let key: string;
    switch (groupBy) {
      case 'topic':
        key = task.primary_topic;
        break;
      case 'assignee':
        key = task.assignee || 'Unassigned';
        break;
      case 'priority':
        key = task.priority.charAt(0).toUpperCase() + task.priority.slice(1);
        break;
      case 'status':
        key = task.status === 'in_progress' ? 'In Progress' :
              task.status.charAt(0).toUpperCase() + task.status.slice(1);
        break;
      default:
        key = 'Other';
    }

    if (!groups.has(key)) {
      groups.set(key, []);
    }
    groups.get(key)!.push(task);
  }

  return groups;
}

function sortTasks(tasks: Task[], sortBy: SortBy): Task[] {
  return [...tasks].sort((a, b) => {
    switch (sortBy) {
      case 'deadline':
        if (!a.deadline && !b.deadline) return 0;
        if (!a.deadline) return 1;
        if (!b.deadline) return -1;
        return new Date(a.deadline).getTime() - new Date(b.deadline).getTime();
      case 'priority': {
        const priorityOrder = { high: 0, medium: 1, low: 2 };
        return priorityOrder[a.priority] - priorityOrder[b.priority];
      }
      case 'created':
        return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
      case 'updated':
        return new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime();
      case 'topic':
        return a.primary_topic.localeCompare(b.primary_topic);
      default:
        return 0;
    }
  });
}

export function TaskList({ tasks, isLoading }: TaskListProps) {
  const [selectedTask, setSelectedTask] = useState<Task | null>(null);
  const [groupBy, setGroupBy] = useState<GroupBy>('none');
  const [sortBy, setSortBy] = useState<SortBy>('priority');
  const [isCompact, setIsCompact] = useState(false);

  const sortedTasks = sortTasks(tasks, sortBy);
  const groupedTasks = groupTasks(sortedTasks, groupBy);

  if (isLoading) {
    return (
      <div className="space-y-4">
        {[1, 2, 3].map((i) => (
          <div key={i} className="animate-pulse">
            <div className="h-32 bg-gray-200 rounded-lg" />
          </div>
        ))}
      </div>
    );
  }

  if (tasks.length === 0) {
    return (
      <div className="text-center py-12">
        <div className="w-16 h-16 mx-auto mb-4 bg-gray-100 rounded-full flex items-center justify-center">
          <ListFilter className="w-8 h-8 text-gray-400" />
        </div>
        <h3 className="text-lg font-medium text-gray-900">No tasks found</h3>
        <p className="mt-1 text-gray-500">Try adjusting your filters to see more tasks.</p>
      </div>
    );
  }

  return (
    <div>
      {/* Controls */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <select
            value={groupBy}
            onChange={(e) => setGroupBy(e.target.value as GroupBy)}
            className="px-3 py-1.5 text-sm border border-gray-300 rounded-lg bg-white focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
          >
            <option value="none">No grouping</option>
            <option value="status">Group by Status</option>
            <option value="topic">Group by Topic</option>
            <option value="assignee">Group by Assignee</option>
            <option value="priority">Group by Priority</option>
          </select>

          <select
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value as SortBy)}
            className="px-3 py-1.5 text-sm border border-gray-300 rounded-lg bg-white focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
          >
            <option value="priority">Sort by Priority</option>
            <option value="deadline">Sort by Deadline</option>
            <option value="created">Sort by Created</option>
            <option value="updated">Sort by Updated</option>
            <option value="topic">Sort by Topic</option>
          </select>
        </div>

        <button
          onClick={() => setIsCompact(!isCompact)}
          className={clsx(
            'p-2 rounded-lg transition-colors',
            isCompact ? 'bg-primary-100 text-primary-700' : 'hover:bg-gray-100 text-gray-500'
          )}
          title={isCompact ? 'Expanded view' : 'Compact view'}
        >
          <LayoutGrid className="w-5 h-5" />
        </button>
      </div>

      {/* Task Groups */}
      <div className="space-y-6">
        {Array.from(groupedTasks.entries()).map(([groupName, groupTasks]) => (
          <div key={groupName}>
            {groupBy !== 'none' && (
              <div className="flex items-center gap-2 mb-3">
                <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">
                  {groupName}
                </h3>
                <span className="px-2 py-0.5 bg-gray-100 text-gray-600 rounded-full text-xs font-medium">
                  {groupTasks.length}
                </span>
              </div>
            )}

            <div className={clsx(
              'space-y-3',
              isCompact && 'grid grid-cols-1 md:grid-cols-2 gap-3 space-y-0'
            )}>
              {groupTasks.map((task) => (
                <TaskCard
                  key={task.id}
                  task={task}
                  onClick={() => setSelectedTask(task)}
                  compact={isCompact}
                />
              ))}
            </div>
          </div>
        ))}
      </div>

      {/* Task Detail Drawer */}
      {selectedTask && (
        <TaskDetail
          task={selectedTask}
          onClose={() => setSelectedTask(null)}
        />
      )}
    </div>
  );
}
