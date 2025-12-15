import { format, isPast, isToday, isTomorrow, parseISO } from 'date-fns';
import { Calendar, User, Tag, ChevronRight, AlertCircle, FileText, CheckCircle2, Clock, Circle } from 'lucide-react';
import { clsx } from 'clsx';
import type { Task } from '@/types';

interface TaskCardProps {
  task: Task;
  onClick?: () => void;
  compact?: boolean;
}

const priorityColors = {
  high: 'border-l-red-500 bg-red-50',
  medium: 'border-l-yellow-500 bg-yellow-50',
  low: 'border-l-green-500 bg-green-50',
};

const priorityBadgeColors = {
  high: 'bg-red-100 text-red-800',
  medium: 'bg-yellow-100 text-yellow-800',
  low: 'bg-green-100 text-green-800',
};

const statusConfig = {
  pending: { icon: Circle, color: 'text-gray-400', label: 'Pending' },
  in_progress: { icon: Clock, color: 'text-blue-500', label: 'In Progress' },
  completed: { icon: CheckCircle2, color: 'text-green-500', label: 'Completed' },
};

function formatDeadline(deadline: string | null): { text: string; isOverdue: boolean; isUrgent: boolean } {
  if (!deadline) return { text: 'No deadline', isOverdue: false, isUrgent: false };

  const date = parseISO(deadline);

  if (isToday(date)) return { text: 'Today', isOverdue: false, isUrgent: true };
  if (isTomorrow(date)) return { text: 'Tomorrow', isOverdue: false, isUrgent: true };
  if (isPast(date)) return { text: `Overdue: ${format(date, 'MMM d')}`, isOverdue: true, isUrgent: false };

  return { text: format(date, 'MMM d, yyyy'), isOverdue: false, isUrgent: false };
}

export function TaskCard({ task, onClick, compact = false }: TaskCardProps) {
  const deadline = formatDeadline(task.deadline);
  const StatusIcon = statusConfig[task.status].icon;
  const isCompleted = task.status === 'completed';

  if (compact) {
    return (
      <div
        className={clsx(
          'p-3 border-l-4 rounded-r-lg cursor-pointer transition-all hover:shadow-md',
          isCompleted ? 'border-l-gray-300 bg-gray-50 opacity-75' : priorityColors[task.priority]
        )}
        onClick={onClick}
      >
        <div className="flex items-start gap-2">
          <StatusIcon className={clsx('w-4 h-4 mt-0.5 flex-shrink-0', statusConfig[task.status].color)} />
          <div className="flex-1 min-w-0">
            <p className={clsx(
              'text-sm line-clamp-2',
              isCompleted ? 'text-gray-500 line-through' : 'text-gray-900'
            )}>
              {task.description}
            </p>
            <div className="mt-2 flex items-center gap-3 text-xs text-gray-500">
              {task.assignee && (
                <span className="flex items-center gap-1">
                  <User className="w-3 h-3" />
                  {task.assignee}
                </span>
              )}
              {task.deadline && !isCompleted && (
                <span className={clsx(
                  'flex items-center gap-1',
                  deadline.isOverdue && 'text-red-600 font-medium',
                  deadline.isUrgent && 'text-orange-600 font-medium'
                )}>
                  <Calendar className="w-3 h-3" />
                  {deadline.text}
                </span>
              )}
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div
      className={clsx(
        'p-4 border-l-4 rounded-lg bg-white shadow-sm cursor-pointer transition-all hover:shadow-md animate-fade-in',
        isCompleted ? 'border-l-gray-300 opacity-75' : priorityColors[task.priority]
      )}
      onClick={onClick}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-start gap-3 flex-1 min-w-0">
          <StatusIcon className={clsx('w-5 h-5 mt-0.5 flex-shrink-0', statusConfig[task.status].color)} />
          <div className="flex-1 min-w-0">
            <p className={clsx(
              'font-medium',
              isCompleted ? 'text-gray-500 line-through' : 'text-gray-900'
            )}>
              {task.description}
            </p>

            <div className="mt-3 flex flex-wrap items-center gap-3 text-sm text-gray-600">
              {task.assignee ? (
                <span className="flex items-center gap-1.5">
                  <User className="w-4 h-4 text-gray-400" />
                  {task.assignee}
                </span>
              ) : (
                <span className="flex items-center gap-1.5 text-gray-400 italic">
                  <User className="w-4 h-4" />
                  Unassigned
                </span>
              )}

              {!isCompleted && (
                <span className={clsx(
                  'flex items-center gap-1.5',
                  deadline.isOverdue && 'text-red-600 font-medium',
                  deadline.isUrgent && 'text-orange-600 font-medium'
                )}>
                  {deadline.isOverdue && <AlertCircle className="w-4 h-4" />}
                  {!deadline.isOverdue && <Calendar className="w-4 h-4 text-gray-400" />}
                  {deadline.text}
                </span>
              )}

              <span className={clsx(
                'px-2 py-0.5 rounded-full text-xs font-medium',
                priorityBadgeColors[task.priority]
              )}>
                {task.priority}
              </span>

              <span className={clsx(
                'px-2 py-0.5 rounded-full text-xs font-medium',
                task.status === 'completed' && 'bg-green-100 text-green-800',
                task.status === 'in_progress' && 'bg-blue-100 text-blue-800',
                task.status === 'pending' && 'bg-gray-100 text-gray-600'
              )}>
                {statusConfig[task.status].label}
              </span>
            </div>

            <div className="mt-3 flex flex-wrap items-center gap-2">
              <span className="inline-flex items-center gap-1 px-2 py-1 bg-primary-100 text-primary-800 rounded text-xs font-medium">
                <Tag className="w-3 h-3" />
                {task.primary_topic}
              </span>
              {task.secondary_topics.slice(0, 2).map((topic) => (
                <span
                  key={topic}
                  className="px-2 py-1 bg-gray-100 text-gray-600 rounded text-xs"
                >
                  {topic}
                </span>
              ))}
              {task.secondary_topics.length > 2 && (
                <span className="text-xs text-gray-400">
                  +{task.secondary_topics.length - 2} more
                </span>
              )}
            </div>
          </div>
        </div>

        <ChevronRight className="w-5 h-5 text-gray-400 flex-shrink-0" />
      </div>

      {task.source_transcript_title && (
        <div className="mt-3 pt-3 border-t border-gray-100 flex items-center gap-2 text-xs text-gray-500">
          <FileText className="w-3.5 h-3.5" />
          <span className="truncate">From: {task.source_transcript_title}</span>
        </div>
      )}
    </div>
  );
}
