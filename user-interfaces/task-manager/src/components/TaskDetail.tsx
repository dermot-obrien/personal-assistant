import { format, parseISO } from 'date-fns';
import { X, Calendar, User, Tag, FileText, Clock, Link2, CheckCircle2, RotateCcw, Trash2, Edit, MessageSquare } from 'lucide-react';
import { clsx } from 'clsx';
import type { Task } from '@/types';
import { useCompleteTask, useReopenTask, useDeleteTask } from '@/hooks/useTasks';

interface TaskDetailProps {
  task: Task;
  onClose: () => void;
  onEdit?: () => void;
}

const priorityColors = {
  high: 'bg-red-100 text-red-800 border-red-200',
  medium: 'bg-yellow-100 text-yellow-800 border-yellow-200',
  low: 'bg-green-100 text-green-800 border-green-200',
};

const statusColors = {
  pending: 'bg-gray-100 text-gray-800 border-gray-200',
  in_progress: 'bg-blue-100 text-blue-800 border-blue-200',
  completed: 'bg-green-100 text-green-800 border-green-200',
};

const statusLabels = {
  pending: 'Pending',
  in_progress: 'In Progress',
  completed: 'Completed',
};

export function TaskDetail({ task, onClose, onEdit }: TaskDetailProps) {
  const completeMutation = useCompleteTask();
  const reopenMutation = useReopenTask();
  const deleteMutation = useDeleteTask();

  const isCompleted = task.status === 'completed';
  const isLoading = completeMutation.isPending || reopenMutation.isPending || deleteMutation.isPending;

  const handleComplete = async () => {
    await completeMutation.mutateAsync(task.id);
  };

  const handleReopen = async () => {
    await reopenMutation.mutateAsync(task.id);
  };

  const handleDelete = async () => {
    if (confirm('Are you sure you want to delete this task?')) {
      await deleteMutation.mutateAsync(task.id);
      onClose();
    }
  };

  return (
    <div className="fixed inset-0 z-50 overflow-hidden">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />

      <div className="absolute right-0 top-0 bottom-0 w-full max-w-lg bg-white shadow-xl animate-slide-up">
        <div className="h-full flex flex-col">
          {/* Header */}
          <div className="flex items-center justify-between p-4 border-b">
            <h2 className="text-lg font-semibold text-gray-900">Task Details</h2>
            <div className="flex items-center gap-2">
              {onEdit && (
                <button
                  onClick={onEdit}
                  className="p-2 hover:bg-gray-100 rounded-lg transition-colors"
                  title="Edit task"
                >
                  <Edit className="w-5 h-5 text-gray-500" />
                </button>
              )}
              <button
                onClick={onClose}
                className="p-2 hover:bg-gray-100 rounded-lg transition-colors"
              >
                <X className="w-5 h-5 text-gray-500" />
              </button>
            </div>
          </div>

          {/* Content */}
          <div className="flex-1 overflow-y-auto p-6">
            {/* Status & Priority Badges */}
            <div className="flex flex-wrap gap-2 mb-4">
              <span className={clsx(
                'inline-flex items-center px-3 py-1 rounded-full text-sm font-medium border',
                statusColors[task.status]
              )}>
                {statusLabels[task.status]}
              </span>
              <span className={clsx(
                'inline-flex items-center px-3 py-1 rounded-full text-sm font-medium border',
                priorityColors[task.priority]
              )}>
                {task.priority.charAt(0).toUpperCase() + task.priority.slice(1)} Priority
              </span>
            </div>

            {/* Description */}
            <div className="mb-6">
              <h3 className={clsx(
                'text-xl font-medium leading-relaxed',
                isCompleted ? 'text-gray-500 line-through' : 'text-gray-900'
              )}>
                {task.description}
              </h3>
            </div>

            {/* Context */}
            {task.context && (
              <div className="mb-6 p-3 bg-blue-50 border border-blue-200 rounded-lg">
                <p className="text-sm text-blue-800">{task.context}</p>
              </div>
            )}

            {/* Metadata Grid */}
            <div className="grid gap-4 mb-6">
              {/* Assignee */}
              <div className="flex items-start gap-3 p-3 bg-gray-50 rounded-lg">
                <User className="w-5 h-5 text-gray-400 mt-0.5" />
                <div>
                  <p className="text-sm font-medium text-gray-500">Assignee</p>
                  <p className="text-gray-900">
                    {task.assignee || <span className="text-gray-400 italic">Unassigned</span>}
                  </p>
                </div>
              </div>

              {/* Deadline */}
              <div className="flex items-start gap-3 p-3 bg-gray-50 rounded-lg">
                <Calendar className="w-5 h-5 text-gray-400 mt-0.5" />
                <div>
                  <p className="text-sm font-medium text-gray-500">Deadline</p>
                  <p className="text-gray-900">
                    {task.deadline
                      ? format(parseISO(task.deadline), 'EEEE, MMMM d, yyyy')
                      : <span className="text-gray-400 italic">No deadline</span>
                    }
                  </p>
                </div>
              </div>

              {/* Primary Topic */}
              <div className="flex items-start gap-3 p-3 bg-gray-50 rounded-lg">
                <Tag className="w-5 h-5 text-gray-400 mt-0.5" />
                <div>
                  <p className="text-sm font-medium text-gray-500">Primary Topic</p>
                  <p className="text-primary-700 font-medium">{task.primary_topic}</p>
                </div>
              </div>

              {/* Secondary Topics */}
              {task.secondary_topics.length > 0 && (
                <div className="flex items-start gap-3 p-3 bg-gray-50 rounded-lg">
                  <Link2 className="w-5 h-5 text-gray-400 mt-0.5" />
                  <div>
                    <p className="text-sm font-medium text-gray-500">Related Topics</p>
                    <div className="flex flex-wrap gap-2 mt-1">
                      {task.secondary_topics.map((topic) => (
                        <span
                          key={topic}
                          className="px-2 py-1 bg-white border border-gray-200 rounded text-sm text-gray-700"
                        >
                          {topic}
                        </span>
                      ))}
                    </div>
                  </div>
                </div>
              )}

              {/* Timestamps */}
              <div className="flex items-start gap-3 p-3 bg-gray-50 rounded-lg">
                <Clock className="w-5 h-5 text-gray-400 mt-0.5" />
                <div className="space-y-1">
                  <div>
                    <p className="text-sm font-medium text-gray-500">Created</p>
                    <p className="text-gray-900">
                      {format(parseISO(task.created_at), 'MMM d, yyyy \'at\' h:mm a')}
                    </p>
                  </div>
                  {task.updated_at !== task.created_at && (
                    <div>
                      <p className="text-sm font-medium text-gray-500">Updated</p>
                      <p className="text-gray-900">
                        {format(parseISO(task.updated_at), 'MMM d, yyyy \'at\' h:mm a')}
                      </p>
                    </div>
                  )}
                  {task.completed_at && (
                    <div>
                      <p className="text-sm font-medium text-gray-500">Completed</p>
                      <p className="text-green-700">
                        {format(parseISO(task.completed_at), 'MMM d, yyyy \'at\' h:mm a')}
                      </p>
                    </div>
                  )}
                </div>
              </div>
            </div>

            {/* Notes */}
            {task.notes.length > 0 && (
              <div className="border-t pt-6">
                <h4 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-4 flex items-center gap-2">
                  <MessageSquare className="w-4 h-4" />
                  Notes ({task.notes.length})
                </h4>
                <div className="space-y-3">
                  {task.notes.map((note, index) => (
                    <div key={index} className="p-3 bg-gray-50 rounded-lg">
                      <p className="text-sm text-gray-700">{note.text}</p>
                      <p className="text-xs text-gray-400 mt-1">
                        {format(parseISO(note.created_at), 'MMM d, yyyy \'at\' h:mm a')}
                      </p>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Source Section */}
            {task.source_transcript_title && (
              <div className="border-t pt-6 mt-6">
                <h4 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-4">
                  Source Transcript
                </h4>

                <div className="p-4 bg-gray-50 rounded-lg">
                  <div className="flex items-start gap-3">
                    <FileText className="w-5 h-5 text-primary-500 mt-0.5" />
                    <div className="flex-1 min-w-0">
                      <p className="font-medium text-gray-900 truncate">
                        {task.source_transcript_title}
                      </p>
                      {task.source_transcript_id && (
                        <p className="text-xs text-gray-400 mt-1">
                          ID: {task.source_transcript_id}
                        </p>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Footer Actions */}
          <div className="p-4 border-t bg-gray-50">
            <div className="flex gap-3">
              <button
                onClick={handleDelete}
                disabled={isLoading}
                className="px-4 py-2 text-red-600 hover:bg-red-50 rounded-lg transition-colors font-medium disabled:opacity-50"
                title="Delete task"
              >
                <Trash2 className="w-5 h-5" />
              </button>
              <button
                onClick={onClose}
                className="flex-1 px-4 py-2 bg-white border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 transition-colors font-medium"
              >
                Close
              </button>
              {isCompleted ? (
                <button
                  onClick={handleReopen}
                  disabled={isLoading}
                  className="flex-1 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors font-medium disabled:opacity-50 flex items-center justify-center gap-2"
                >
                  <RotateCcw className="w-4 h-4" />
                  Reopen
                </button>
              ) : (
                <button
                  onClick={handleComplete}
                  disabled={isLoading}
                  className="flex-1 px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 transition-colors font-medium disabled:opacity-50 flex items-center justify-center gap-2"
                >
                  <CheckCircle2 className="w-4 h-4" />
                  Complete
                </button>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
