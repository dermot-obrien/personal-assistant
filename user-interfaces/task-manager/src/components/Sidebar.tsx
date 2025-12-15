import { useState } from 'react';
import { NavLink } from 'react-router-dom';
import {
  LayoutDashboard,
  ListTodo,
  FolderTree,
  Users,
  Settings,
  ChevronLeft,
  ChevronRight,
  CheckCircle2,
  Clock,
  AlertTriangle
} from 'lucide-react';
import { clsx } from 'clsx';

interface SidebarProps {
  stats?: {
    total: number;
    pending: number;
    in_progress: number;
    completed: number;
    high: number;
    medium: number;
    low: number;
  };
}

const navigation = [
  { name: 'Dashboard', href: '/', icon: LayoutDashboard },
  { name: 'All Tasks', href: '/tasks', icon: ListTodo },
  { name: 'Topics', href: '/topics', icon: FolderTree },
  { name: 'Assignees', href: '/assignees', icon: Users },
];

export function Sidebar({ stats }: SidebarProps) {
  const [isCollapsed, setIsCollapsed] = useState(false);

  return (
    <aside
      className={clsx(
        'bg-gray-900 text-white flex flex-col transition-all duration-300',
        isCollapsed ? 'w-16' : 'w-64'
      )}
    >
      {/* Header */}
      <div className="p-4 border-b border-gray-800">
        <div className="flex items-center justify-between">
          {!isCollapsed && (
            <div>
              <h1 className="text-lg font-bold">Task Manager</h1>
              <p className="text-xs text-gray-400">Consolidated Tasks</p>
            </div>
          )}
          <button
            onClick={() => setIsCollapsed(!isCollapsed)}
            className="p-1.5 hover:bg-gray-800 rounded-lg transition-colors"
          >
            {isCollapsed ? (
              <ChevronRight className="w-5 h-5" />
            ) : (
              <ChevronLeft className="w-5 h-5" />
            )}
          </button>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 p-2">
        <ul className="space-y-1">
          {navigation.map((item) => (
            <li key={item.name}>
              <NavLink
                to={item.href}
                className={({ isActive }) =>
                  clsx(
                    'flex items-center gap-3 px-3 py-2 rounded-lg transition-colors',
                    isActive
                      ? 'bg-primary-600 text-white'
                      : 'text-gray-300 hover:bg-gray-800 hover:text-white'
                  )
                }
              >
                <item.icon className="w-5 h-5 flex-shrink-0" />
                {!isCollapsed && <span>{item.name}</span>}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>

      {/* Stats */}
      {stats && !isCollapsed && (
        <div className="p-4 border-t border-gray-800">
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">
            Quick Stats
          </h3>
          <div className="space-y-2">
            <div className="flex items-center justify-between text-sm">
              <span className="flex items-center gap-2 text-gray-300">
                <CheckCircle2 className="w-4 h-4 text-primary-400" />
                Total Tasks
              </span>
              <span className="font-medium">{stats.total}</span>
            </div>
            <div className="flex items-center justify-between text-sm">
              <span className="flex items-center gap-2 text-gray-300">
                <Clock className="w-4 h-4 text-yellow-400" />
                Pending
              </span>
              <span className="font-medium text-yellow-400">{stats.pending}</span>
            </div>
            <div className="flex items-center justify-between text-sm">
              <span className="flex items-center gap-2 text-gray-300">
                <AlertTriangle className="w-4 h-4 text-blue-400" />
                In Progress
              </span>
              <span className="font-medium text-blue-400">{stats.in_progress}</span>
            </div>
            <div className="flex items-center justify-between text-sm">
              <span className="flex items-center gap-2 text-gray-300">
                <CheckCircle2 className="w-4 h-4 text-green-400" />
                Completed
              </span>
              <span className="font-medium text-green-400">{stats.completed}</span>
            </div>
            <div className="flex items-center justify-between text-sm mt-2 pt-2 border-t border-gray-700">
              <span className="flex items-center gap-2 text-gray-300">
                <AlertTriangle className="w-4 h-4 text-red-400" />
                High Priority
              </span>
              <span className="font-medium text-red-400">{stats.high}</span>
            </div>
          </div>
        </div>
      )}

      {/* Settings */}
      <div className="p-2 border-t border-gray-800">
        <NavLink
          to="/settings"
          className={({ isActive }) =>
            clsx(
              'flex items-center gap-3 px-3 py-2 rounded-lg transition-colors',
              isActive
                ? 'bg-primary-600 text-white'
                : 'text-gray-300 hover:bg-gray-800 hover:text-white'
            )
          }
        >
          <Settings className="w-5 h-5 flex-shrink-0" />
          {!isCollapsed && <span>Settings</span>}
        </NavLink>
      </div>
    </aside>
  );
}
