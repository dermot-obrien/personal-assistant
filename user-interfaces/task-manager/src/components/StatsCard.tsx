import { clsx } from 'clsx';
import type { LucideIcon } from 'lucide-react';

interface StatsCardProps {
  title: string;
  value: number | string;
  subtitle?: string;
  icon: LucideIcon;
  trend?: {
    value: number;
    isPositive: boolean;
  };
  color?: 'primary' | 'red' | 'yellow' | 'green' | 'blue';
}

const colorClasses = {
  primary: {
    bg: 'bg-primary-50',
    icon: 'text-primary-600',
    trend: 'text-primary-600',
  },
  red: {
    bg: 'bg-red-50',
    icon: 'text-red-600',
    trend: 'text-red-600',
  },
  yellow: {
    bg: 'bg-yellow-50',
    icon: 'text-yellow-600',
    trend: 'text-yellow-600',
  },
  green: {
    bg: 'bg-green-50',
    icon: 'text-green-600',
    trend: 'text-green-600',
  },
  blue: {
    bg: 'bg-blue-50',
    icon: 'text-blue-600',
    trend: 'text-blue-600',
  },
};

export function StatsCard({ title, value, subtitle, icon: Icon, trend, color = 'primary' }: StatsCardProps) {
  const colors = colorClasses[color];

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5 hover:shadow-md transition-shadow">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-sm font-medium text-gray-500">{title}</p>
          <p className="mt-2 text-3xl font-bold text-gray-900">{value}</p>
          {subtitle && (
            <p className="mt-1 text-sm text-gray-500">{subtitle}</p>
          )}
          {trend && (
            <p className={clsx(
              'mt-2 text-sm font-medium',
              trend.isPositive ? 'text-green-600' : 'text-red-600'
            )}>
              {trend.isPositive ? '+' : ''}{trend.value}%
              <span className="text-gray-500 font-normal"> from last week</span>
            </p>
          )}
        </div>
        <div className={clsx('p-3 rounded-lg', colors.bg)}>
          <Icon className={clsx('w-6 h-6', colors.icon)} />
        </div>
      </div>
    </div>
  );
}
