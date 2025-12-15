import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Sidebar } from '@/components';
import { Dashboard, Tasks, Topics, Assignees, Settings } from '@/pages';
import { useStats } from '@/hooks/useTasks';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});

function AppLayout() {
  const { data: statsData } = useStats();

  const stats = statsData
    ? {
        total: statsData.total_tasks,
        pending: statsData.by_status.pending || 0,
        in_progress: statsData.by_status.in_progress || 0,
        completed: statsData.by_status.completed || 0,
        high: statsData.by_priority.high || 0,
        medium: statsData.by_priority.medium || 0,
        low: statsData.by_priority.low || 0,
      }
    : undefined;

  return (
    <div className="flex h-screen bg-gray-100">
      <Sidebar stats={stats} />
      <main className="flex-1 overflow-hidden">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/tasks" element={<Tasks />} />
          <Route path="/topics" element={<Topics />} />
          <Route path="/assignees" element={<Assignees />} />
          <Route path="/settings" element={<Settings />} />
        </Routes>
      </main>
    </div>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AppLayout />
      </BrowserRouter>
    </QueryClientProvider>
  );
}
