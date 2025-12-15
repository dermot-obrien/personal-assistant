import type {
  Task,
  TaskListResponse,
  TaskStatsResponse,
  CreateTaskPayload,
  UpdateTaskPayload,
  ImportResponse,
  FilterState,
} from '@/types';

const API_BASE = import.meta.env.VITE_API_BASE || '/api/tasks';

class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = 'ApiError';
  }
}

async function fetchApi<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const url = `${API_BASE}${endpoint}`;
  const response = await fetch(url, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ error: response.statusText }));
    throw new ApiError(response.status, error.error || 'Request failed');
  }

  return response.json();
}

// Task CRUD operations
export async function listTasks(
  filters: Partial<FilterState> = {},
  pagination?: { limit?: number; offset?: number }
): Promise<TaskListResponse> {
  const params = new URLSearchParams();

  if (filters.status) params.set('status', filters.status);
  if (filters.topic) params.set('topic', filters.topic);
  if (filters.assignee) params.set('assignee', filters.assignee);
  if (filters.priority) params.set('priority', filters.priority);
  if (filters.search) params.set('q', filters.search);
  if (pagination?.limit) params.set('limit', pagination.limit.toString());
  if (pagination?.offset) params.set('offset', pagination.offset.toString());

  const query = params.toString();
  return fetchApi<TaskListResponse>(`/${query ? `?${query}` : ''}`);
}

export async function getTask(taskId: string): Promise<Task> {
  return fetchApi<Task>(`/${taskId}`);
}

export async function createTask(payload: CreateTaskPayload): Promise<Task> {
  return fetchApi<Task>('/', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function updateTask(taskId: string, payload: UpdateTaskPayload): Promise<Task> {
  return fetchApi<Task>(`/${taskId}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
}

export async function deleteTask(taskId: string): Promise<{ success: boolean; task_id: string }> {
  return fetchApi(`/${taskId}`, {
    method: 'DELETE',
  });
}

export async function completeTask(taskId: string): Promise<Task> {
  return fetchApi<Task>(`/${taskId}/complete`, {
    method: 'POST',
  });
}

export async function reopenTask(taskId: string): Promise<Task> {
  return fetchApi<Task>(`/${taskId}/reopen`, {
    method: 'POST',
  });
}

// Statistics
export async function getStats(): Promise<TaskStatsResponse> {
  return fetchApi<TaskStatsResponse>('/stats');
}

// Import from consolidated tasks
export async function importTasks(options: { dryRun?: boolean; replace?: boolean } = {}): Promise<ImportResponse> {
  const params = new URLSearchParams();
  if (options.dryRun) params.set('dry_run', 'true');
  if (options.replace) params.set('replace', 'true');

  const query = params.toString();
  return fetchApi<ImportResponse>(`/import${query ? `?${query}` : ''}`, {
    method: 'POST',
  });
}

// Mock data for development
export function getMockTasks(): TaskListResponse {
  const tasks: Task[] = [
    {
      id: 'task_abc123def456',
      description: 'Review and approve the Q1 budget proposal by Friday',
      assignee: 'John',
      deadline: '2024-12-15',
      priority: 'high',
      primary_topic: 'Work/Finance',
      secondary_topics: ['Work/Projects/Alpha'],
      status: 'pending',
      context: 'Discussed in team standup',
      source_transcript_id: 'transcript-001',
      source_transcript_title: 'Team Standup - December 2024',
      created_at: '2024-12-10T09:31:00Z',
      updated_at: '2024-12-10T09:31:00Z',
      completed_at: null,
      notes: [],
    },
    {
      id: 'task_def456ghi789',
      description: 'Schedule meeting with design team to discuss new UI components',
      assignee: 'Sarah',
      deadline: '2024-12-14',
      priority: 'medium',
      primary_topic: 'Work/Projects/Alpha',
      secondary_topics: ['Work/Design'],
      status: 'in_progress',
      context: null,
      source_transcript_id: 'transcript-001',
      source_transcript_title: 'Team Standup - December 2024',
      created_at: '2024-12-10T09:31:00Z',
      updated_at: '2024-12-11T14:00:00Z',
      completed_at: null,
      notes: [{ text: 'Sent calendar invite', created_at: '2024-12-11T14:00:00Z' }],
    },
    {
      id: 'task_ghi789jkl012',
      description: 'Fix the authentication bug in the mobile app',
      assignee: 'Mike',
      deadline: '2024-12-13',
      priority: 'high',
      primary_topic: 'Work/Engineering',
      secondary_topics: ['Work/Projects/Mobile'],
      status: 'completed',
      context: 'Critical issue affecting users',
      source_transcript_id: 'transcript-001',
      source_transcript_title: 'Team Standup - December 2024',
      created_at: '2024-12-10T09:31:00Z',
      updated_at: '2024-12-12T16:30:00Z',
      completed_at: '2024-12-12T16:30:00Z',
      notes: [],
    },
    {
      id: 'task_jkl012mno345',
      description: 'Update project documentation with new API endpoints',
      assignee: null,
      deadline: null,
      priority: 'low',
      primary_topic: 'Work/Documentation',
      secondary_topics: [],
      status: 'pending',
      context: null,
      source_transcript_id: 'transcript-001',
      source_transcript_title: 'Team Standup - December 2024',
      created_at: '2024-12-10T09:31:00Z',
      updated_at: '2024-12-10T09:31:00Z',
      completed_at: null,
      notes: [],
    },
    {
      id: 'task_mno345pqr678',
      description: 'Create wireframes for the new dashboard feature',
      assignee: 'Emily',
      deadline: '2024-12-18',
      priority: 'high',
      primary_topic: 'Work/Design',
      secondary_topics: ['Work/Projects/Alpha'],
      status: 'pending',
      context: null,
      source_transcript_id: 'transcript-002',
      source_transcript_title: 'Product Planning Session',
      created_at: '2024-12-11T15:01:00Z',
      updated_at: '2024-12-11T15:01:00Z',
      completed_at: null,
      notes: [],
    },
    {
      id: 'task_pqr678stu901',
      description: 'Set up analytics tracking for user engagement metrics',
      assignee: 'John',
      deadline: '2024-12-20',
      priority: 'medium',
      primary_topic: 'Work/Analytics',
      secondary_topics: ['Work/Engineering'],
      status: 'pending',
      context: null,
      source_transcript_id: 'transcript-002',
      source_transcript_title: 'Product Planning Session',
      created_at: '2024-12-11T15:01:00Z',
      updated_at: '2024-12-11T15:01:00Z',
      completed_at: null,
      notes: [],
    },
    {
      id: 'task_stu901vwx234',
      description: 'Research competitor features and prepare comparison report',
      assignee: 'Sarah',
      deadline: '2024-12-22',
      priority: 'medium',
      primary_topic: 'Work/Research',
      secondary_topics: ['Work/Projects/Alpha'],
      status: 'pending',
      context: null,
      source_transcript_id: 'transcript-002',
      source_transcript_title: 'Product Planning Session',
      created_at: '2024-12-11T15:01:00Z',
      updated_at: '2024-12-11T15:01:00Z',
      completed_at: null,
      notes: [],
    },
    {
      id: 'task_vwx234yza567',
      description: 'Plan Q1 marketing campaign strategy',
      assignee: null,
      deadline: '2024-12-30',
      priority: 'medium',
      primary_topic: 'Work/Marketing',
      secondary_topics: [],
      status: 'pending',
      context: null,
      source_transcript_id: 'transcript-002',
      source_transcript_title: 'Product Planning Session',
      created_at: '2024-12-11T15:01:00Z',
      updated_at: '2024-12-11T15:01:00Z',
      completed_at: null,
      notes: [],
    },
    {
      id: 'task_yza567bcd890',
      description: 'Finalize partnership agreement with vendor',
      assignee: 'Mike',
      deadline: '2024-12-17',
      priority: 'high',
      primary_topic: 'Work/Business',
      secondary_topics: ['Work/Legal'],
      status: 'pending',
      context: null,
      source_transcript_id: 'transcript-002',
      source_transcript_title: 'Product Planning Session',
      created_at: '2024-12-11T15:01:00Z',
      updated_at: '2024-12-11T15:01:00Z',
      completed_at: null,
      notes: [],
    },
    {
      id: 'task_bcd890efg123',
      description: 'Complete online course on machine learning fundamentals',
      assignee: null,
      deadline: '2024-12-31',
      priority: 'medium',
      primary_topic: 'Personal/Learning',
      secondary_topics: ['Personal/Goals'],
      status: 'in_progress',
      context: null,
      source_transcript_id: 'transcript-003',
      source_transcript_title: 'Personal Goals Review',
      created_at: '2024-12-12T10:31:00Z',
      updated_at: '2024-12-13T09:00:00Z',
      completed_at: null,
      notes: [{ text: 'Started module 3', created_at: '2024-12-13T09:00:00Z' }],
    },
    {
      id: 'task_efg123hij456',
      description: 'Start daily meditation practice - 10 minutes each morning',
      assignee: null,
      deadline: null,
      priority: 'low',
      primary_topic: 'Personal/Health',
      secondary_topics: ['Personal/Habits'],
      status: 'pending',
      context: null,
      source_transcript_id: 'transcript-003',
      source_transcript_title: 'Personal Goals Review',
      created_at: '2024-12-12T10:31:00Z',
      updated_at: '2024-12-12T10:31:00Z',
      completed_at: null,
      notes: [],
    },
    {
      id: 'task_hij456klm789',
      description: 'Schedule annual health checkup appointment',
      assignee: null,
      deadline: '2024-12-20',
      priority: 'medium',
      primary_topic: 'Personal/Health',
      secondary_topics: [],
      status: 'pending',
      context: null,
      source_transcript_id: 'transcript-003',
      source_transcript_title: 'Personal Goals Review',
      created_at: '2024-12-12T10:31:00Z',
      updated_at: '2024-12-12T10:31:00Z',
      completed_at: null,
      notes: [],
    },
  ];

  return {
    total: tasks.length,
    limit: 100,
    offset: 0,
    count: tasks.length,
    tasks,
  };
}

export function getMockStats(): TaskStatsResponse {
  return {
    total_tasks: 12,
    last_updated: new Date().toISOString(),
    by_status: {
      pending: 9,
      in_progress: 2,
      completed: 1,
    },
    by_priority: {
      high: 4,
      medium: 6,
      low: 2,
    },
    topics: [
      'Work/Finance',
      'Work/Projects/Alpha',
      'Work/Engineering',
      'Work/Documentation',
      'Work/Design',
      'Work/Analytics',
      'Work/Research',
      'Work/Marketing',
      'Work/Business',
      'Personal/Learning',
      'Personal/Health',
    ],
    assignees: ['John', 'Sarah', 'Mike', 'Emily', 'Unassigned'],
    topic_counts: {
      'Work/Finance': 1,
      'Work/Projects/Alpha': 2,
      'Work/Engineering': 1,
      'Work/Documentation': 1,
      'Work/Design': 1,
      'Work/Analytics': 1,
      'Work/Research': 1,
      'Work/Marketing': 1,
      'Work/Business': 1,
      'Personal/Learning': 1,
      'Personal/Health': 2,
    },
    assignee_counts: {
      John: 2,
      Sarah: 2,
      Mike: 2,
      Emily: 1,
      Unassigned: 5,
    },
  };
}
