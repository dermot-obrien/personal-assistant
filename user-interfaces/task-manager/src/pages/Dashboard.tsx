import { useMemo } from 'react';
import { Link } from 'react-router-dom';
import { format, parseISO, isPast, isToday, addDays, isWithinInterval } from 'date-fns';
import {
  ListTodo,
  AlertTriangle,
  Clock,
  CheckCircle2,
  Users,
  FolderTree,
  ArrowRight,
  Circle,
  PlayCircle,
} from 'lucide-react';
import { StatsCard, TaskCard } from '@/components';
import { useTasks, useStats } from '@/hooks/useTasks';

export function Dashboard() {
  const { data: statsData, isLoading: statsLoading } = useStats();
  const { data: tasksData, isLoading: tasksLoading } = useTasks({
    status: null,
    topic: null,
    assignee: null,
    priority: null,
    search: '',
  });

  const isLoading = statsLoading || tasksLoading;

  const dashboardStats = useMemo(() => {
    if (!statsData || !tasksData) return null;

    const tasks = tasksData.tasks;
    const now = new Date();
    const weekFromNow = addDays(now, 7);

    // Only consider non-completed tasks for urgent/overdue
    const activeTasks = tasks.filter(t => t.status !== 'completed');

    const overdueTasks = activeTasks.filter(t =>
      t.deadline && isPast(parseISO(t.deadline)) && !isToday(parseISO(t.deadline))
    );

    const dueSoonTasks = activeTasks.filter(t => {
      if (!t.deadline) return false;
      const deadline = parseISO(t.deadline);
      return isWithinInterval(deadline, { start: now, end: weekFromNow });
    });

    // Get urgent tasks (high priority pending/in_progress, or due soon, or overdue)
    const urgentTasks = activeTasks
      .filter(t =>
        t.priority === 'high' ||
        dueSoonTasks.includes(t) ||
        overdueTasks.includes(t)
      )
      .slice(0, 5);

    // Recent tasks by updated_at
    const recentTasks = [...tasks]
      .sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())
      .slice(0, 5);

    return {
      total: statsData.total_tasks,
      byStatus: statsData.by_status,
      byPriority: statsData.by_priority,
      overdue: overdueTasks.length,
      dueSoon: dueSoonTasks.length,
      assigneeCount: statsData.assignees.length,
      topicCount: statsData.topics.length,
      urgentTasks,
      recentTasks,
      lastUpdated: statsData.last_updated,
    };
  }, [statsData, tasksData]);

  if (isLoading) {
    return (
      <div className="p-6">
        <div className="animate-pulse space-y-6">
          <div className="h-8 bg-gray-200 rounded w-48" />
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            {[1, 2, 3, 4].map(i => (
              <div key={i} className="h-32 bg-gray-200 rounded-xl" />
            ))}
          </div>
        </div>
      </div>
    );
  }

  if (!dashboardStats) return null;

  const pending = dashboardStats.byStatus.pending || 0;
  const inProgress = dashboardStats.byStatus.in_progress || 0;
  const completed = dashboardStats.byStatus.completed || 0;
  const high = dashboardStats.byPriority.high || 0;
  const medium = dashboardStats.byPriority.medium || 0;
  const low = dashboardStats.byPriority.low || 0;

  return (
    <div className="p-6 space-y-6 overflow-y-auto">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>
        <p className="text-gray-500 mt-1">
          Overview of your managed tasks
          {dashboardStats.lastUpdated && (
            <span className="text-gray-400">
              {' '}· Updated {format(parseISO(dashboardStats.lastUpdated), 'MMM d, h:mm a')}
            </span>
          )}
        </p>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatsCard
          title="Total Tasks"
          value={dashboardStats.total}
          subtitle={`${pending + inProgress} active`}
          icon={ListTodo}
          color="primary"
        />
        <StatsCard
          title="High Priority"
          value={high}
          subtitle={dashboardStats.overdue > 0 ? `${dashboardStats.overdue} overdue` : 'None overdue'}
          icon={AlertTriangle}
          color="red"
        />
        <StatsCard
          title="In Progress"
          value={inProgress}
          subtitle={`${dashboardStats.dueSoon} due this week`}
          icon={Clock}
          color="yellow"
        />
        <StatsCard
          title="Completed"
          value={completed}
          subtitle={`${Math.round((completed / dashboardStats.total) * 100 || 0)}% completion rate`}
          icon={CheckCircle2}
          color="green"
        />
      </div>

      {/* Status & Priority Breakdown */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Status Breakdown */}
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <h2 className="text-lg font-semibold text-gray-900 mb-4">Status Breakdown</h2>
          <div className="space-y-3">
            <div className="flex items-center gap-3">
              <div className="flex-1">
                <div className="flex h-3 rounded-full overflow-hidden bg-gray-100">
                  <div
                    className="bg-gray-400 transition-all"
                    style={{ width: `${(pending / dashboardStats.total) * 100}%` }}
                  />
                  <div
                    className="bg-blue-500 transition-all"
                    style={{ width: `${(inProgress / dashboardStats.total) * 100}%` }}
                  />
                  <div
                    className="bg-green-500 transition-all"
                    style={{ width: `${(completed / dashboardStats.total) * 100}%` }}
                  />
                </div>
              </div>
            </div>
            <div className="flex items-center justify-between text-sm">
              <span className="flex items-center gap-1.5">
                <Circle className="w-3 h-3 text-gray-400" />
                Pending ({pending})
              </span>
              <span className="flex items-center gap-1.5">
                <PlayCircle className="w-3 h-3 text-blue-500" />
                In Progress ({inProgress})
              </span>
              <span className="flex items-center gap-1.5">
                <CheckCircle2 className="w-3 h-3 text-green-500" />
                Completed ({completed})
              </span>
            </div>
          </div>
        </div>

        {/* Priority Breakdown */}
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <h2 className="text-lg font-semibold text-gray-900 mb-4">Priority Breakdown</h2>
          <div className="space-y-3">
            <div className="flex items-center gap-3">
              <div className="flex-1">
                <div className="flex h-3 rounded-full overflow-hidden bg-gray-100">
                  <div
                    className="bg-red-500 transition-all"
                    style={{ width: `${(high / dashboardStats.total) * 100}%` }}
                  />
                  <div
                    className="bg-yellow-500 transition-all"
                    style={{ width: `${(medium / dashboardStats.total) * 100}%` }}
                  />
                  <div
                    className="bg-green-500 transition-all"
                    style={{ width: `${(low / dashboardStats.total) * 100}%` }}
                  />
                </div>
              </div>
            </div>
            <div className="flex items-center justify-between text-sm">
              <span className="flex items-center gap-1.5">
                <span className="w-3 h-3 rounded-full bg-red-500" />
                High ({high})
              </span>
              <span className="flex items-center gap-1.5">
                <span className="w-3 h-3 rounded-full bg-yellow-500" />
                Medium ({medium})
              </span>
              <span className="flex items-center gap-1.5">
                <span className="w-3 h-3 rounded-full bg-green-500" />
                Low ({low})
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Two Column Layout - Tasks */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Urgent Tasks */}
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <div className="p-4 border-b border-gray-200 flex items-center justify-between">
            <div>
              <h2 className="font-semibold text-gray-900">Urgent Tasks</h2>
              <p className="text-sm text-gray-500">High priority or due soon</p>
            </div>
            <Link
              to="/tasks?priority=high"
              className="text-sm text-primary-600 hover:text-primary-700 flex items-center gap-1"
            >
              View all <ArrowRight className="w-4 h-4" />
            </Link>
          </div>
          <div className="divide-y divide-gray-100">
            {dashboardStats.urgentTasks.length > 0 ? (
              dashboardStats.urgentTasks.map((task) => (
                <div key={task.id} className="p-4">
                  <TaskCard task={task} compact />
                </div>
              ))
            ) : (
              <div className="p-8 text-center text-gray-500">
                <CheckCircle2 className="w-12 h-12 mx-auto mb-3 text-green-400" />
                <p>No urgent tasks!</p>
              </div>
            )}
          </div>
        </div>

        {/* Recent Tasks */}
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <div className="p-4 border-b border-gray-200 flex items-center justify-between">
            <div>
              <h2 className="font-semibold text-gray-900">Recently Updated</h2>
              <p className="text-sm text-gray-500">Latest activity on tasks</p>
            </div>
            <Link
              to="/tasks"
              className="text-sm text-primary-600 hover:text-primary-700 flex items-center gap-1"
            >
              View all <ArrowRight className="w-4 h-4" />
            </Link>
          </div>
          <div className="divide-y divide-gray-100">
            {dashboardStats.recentTasks.map((task) => (
              <div key={task.id} className="p-4">
                <TaskCard task={task} compact />
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Quick Links */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Link
          to="/topics"
          className="flex items-center gap-4 p-4 bg-white rounded-xl border border-gray-200 hover:border-primary-300 hover:shadow-md transition-all"
        >
          <div className="p-3 bg-primary-50 rounded-lg">
            <FolderTree className="w-6 h-6 text-primary-600" />
          </div>
          <div>
            <h3 className="font-semibold text-gray-900">Browse by Topic</h3>
            <p className="text-sm text-gray-500">{dashboardStats.topicCount} topics</p>
          </div>
        </Link>

        <Link
          to="/assignees"
          className="flex items-center gap-4 p-4 bg-white rounded-xl border border-gray-200 hover:border-primary-300 hover:shadow-md transition-all"
        >
          <div className="p-3 bg-blue-50 rounded-lg">
            <Users className="w-6 h-6 text-blue-600" />
          </div>
          <div>
            <h3 className="font-semibold text-gray-900">View by Assignee</h3>
            <p className="text-sm text-gray-500">{dashboardStats.assigneeCount} team members</p>
          </div>
        </Link>
      </div>
    </div>
  );
}
