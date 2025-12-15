import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  listTasks,
  getTask,
  createTask,
  updateTask,
  deleteTask,
  completeTask,
  reopenTask,
  getStats,
  importTasks,
  getMockTasks,
  getMockStats,
} from '@/api/tasks';
import type {
  Task,
  TaskListResponse,
  TaskStatsResponse,
  FilterState,
  CreateTaskPayload,
  UpdateTaskPayload,
} from '@/types';

const USE_MOCK = import.meta.env.VITE_USE_MOCK === 'true';

// List tasks with filtering
export function useTasks(filters: FilterState, pagination?: { limit?: number; offset?: number }) {
  return useQuery<TaskListResponse>({
    queryKey: ['tasks', filters, pagination],
    queryFn: async () => {
      if (USE_MOCK) {
        const mock = getMockTasks();
        let tasks = [...mock.tasks];

        // Apply filters
        if (filters.status) {
          tasks = tasks.filter(t => t.status === filters.status);
        }
        if (filters.topic) {
          tasks = tasks.filter(t => t.primary_topic.startsWith(filters.topic!));
        }
        if (filters.assignee) {
          if (filters.assignee === 'Unassigned') {
            tasks = tasks.filter(t => !t.assignee);
          } else {
            tasks = tasks.filter(t => t.assignee === filters.assignee);
          }
        }
        if (filters.priority) {
          tasks = tasks.filter(t => t.priority === filters.priority);
        }
        if (filters.search) {
          const search = filters.search.toLowerCase();
          tasks = tasks.filter(t =>
            t.description.toLowerCase().includes(search) ||
            t.primary_topic.toLowerCase().includes(search) ||
            t.assignee?.toLowerCase().includes(search)
          );
        }

        return {
          total: tasks.length,
          limit: pagination?.limit || 100,
          offset: pagination?.offset || 0,
          count: tasks.length,
          tasks,
        };
      }

      return listTasks(filters, pagination);
    },
    staleTime: 30000,
  });
}

// Get single task
export function useTask(taskId: string | null) {
  return useQuery<Task>({
    queryKey: ['task', taskId],
    queryFn: async () => {
      if (USE_MOCK) {
        const mock = getMockTasks();
        const task = mock.tasks.find(t => t.id === taskId);
        if (!task) throw new Error('Task not found');
        return task;
      }
      return getTask(taskId!);
    },
    enabled: !!taskId,
    staleTime: 30000,
  });
}

// Get statistics
export function useStats() {
  return useQuery<TaskStatsResponse>({
    queryKey: ['stats'],
    queryFn: async () => {
      if (USE_MOCK) {
        return getMockStats();
      }
      return getStats();
    },
    staleTime: 60000,
  });
}

// Create task mutation
export function useCreateTask() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (payload: CreateTaskPayload) => {
      if (USE_MOCK) {
        return Promise.resolve({
          id: `task_${Date.now()}`,
          ...payload,
          status: 'pending' as const,
          context: payload.context || null,
          source_transcript_id: payload.source_transcript_id || null,
          source_transcript_title: payload.source_transcript_title || null,
          primary_topic: payload.primary_topic || 'General',
          secondary_topics: payload.secondary_topics || [],
          priority: payload.priority || 'medium',
          assignee: payload.assignee || null,
          deadline: payload.deadline || null,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
          completed_at: null,
          notes: [],
        } as Task);
      }
      return createTask(payload);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tasks'] });
      queryClient.invalidateQueries({ queryKey: ['stats'] });
    },
  });
}

// Update task mutation
export function useUpdateTask() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ taskId, payload }: { taskId: string; payload: UpdateTaskPayload }) => {
      if (USE_MOCK) {
        const mock = getMockTasks();
        const task = mock.tasks.find(t => t.id === taskId);
        if (!task) throw new Error('Task not found');
        return Promise.resolve({ ...task, ...payload, updated_at: new Date().toISOString() });
      }
      return updateTask(taskId, payload);
    },
    onSuccess: (_, { taskId }) => {
      queryClient.invalidateQueries({ queryKey: ['tasks'] });
      queryClient.invalidateQueries({ queryKey: ['task', taskId] });
      queryClient.invalidateQueries({ queryKey: ['stats'] });
    },
  });
}

// Delete task mutation
export function useDeleteTask() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (taskId: string) => {
      if (USE_MOCK) {
        return Promise.resolve({ success: true, task_id: taskId });
      }
      return deleteTask(taskId);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tasks'] });
      queryClient.invalidateQueries({ queryKey: ['stats'] });
    },
  });
}

// Complete task mutation
export function useCompleteTask() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (taskId: string) => {
      if (USE_MOCK) {
        const mock = getMockTasks();
        const task = mock.tasks.find(t => t.id === taskId);
        if (!task) throw new Error('Task not found');
        return Promise.resolve({
          ...task,
          status: 'completed' as const,
          completed_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        });
      }
      return completeTask(taskId);
    },
    onSuccess: (_, taskId) => {
      queryClient.invalidateQueries({ queryKey: ['tasks'] });
      queryClient.invalidateQueries({ queryKey: ['task', taskId] });
      queryClient.invalidateQueries({ queryKey: ['stats'] });
    },
  });
}

// Reopen task mutation
export function useReopenTask() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (taskId: string) => {
      if (USE_MOCK) {
        const mock = getMockTasks();
        const task = mock.tasks.find(t => t.id === taskId);
        if (!task) throw new Error('Task not found');
        return Promise.resolve({
          ...task,
          status: 'pending' as const,
          completed_at: null,
          updated_at: new Date().toISOString(),
        });
      }
      return reopenTask(taskId);
    },
    onSuccess: (_, taskId) => {
      queryClient.invalidateQueries({ queryKey: ['tasks'] });
      queryClient.invalidateQueries({ queryKey: ['task', taskId] });
      queryClient.invalidateQueries({ queryKey: ['stats'] });
    },
  });
}

// Import tasks mutation
export function useImportTasks() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (options: { dryRun?: boolean; replace?: boolean }) => {
      if (USE_MOCK) {
        return Promise.resolve({
          dry_run: options.dryRun || false,
          imported_count: 5,
          skipped_count: 2,
          replaced_count: 0,
          imported: [],
          skipped: [],
          replaced: [],
        });
      }
      return importTasks(options);
    },
    onSuccess: (_, { dryRun }) => {
      if (!dryRun) {
        queryClient.invalidateQueries({ queryKey: ['tasks'] });
        queryClient.invalidateQueries({ queryKey: ['stats'] });
      }
    },
  });
}
