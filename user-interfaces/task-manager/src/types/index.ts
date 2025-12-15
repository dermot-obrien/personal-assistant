// Task structure from task-manager microservice
export interface Task {
  id: string;
  description: string;
  assignee: string | null;
  deadline: string | null;
  priority: 'high' | 'medium' | 'low';
  primary_topic: string;
  secondary_topics: string[];
  status: 'pending' | 'in_progress' | 'completed';
  context: string | null;
  source_transcript_id: string | null;
  source_transcript_title: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  notes: TaskNote[];
}

export interface TaskNote {
  text: string;
  created_at: string;
}

// API Response types for task-manager service
export interface TaskListResponse {
  total: number;
  limit: number;
  offset: number;
  count: number;
  tasks: Task[];
}

export interface TaskStatsResponse {
  total_tasks: number;
  last_updated: string | null;
  by_status: Record<string, number>;
  by_priority: Record<string, number>;
  topics: string[];
  assignees: string[];
  topic_counts: Record<string, number>;
  assignee_counts: Record<string, number>;
}

export interface ImportResponse {
  dry_run: boolean;
  imported_count: number;
  skipped_count: number;
  replaced_count: number;
  imported: Array<{ id: string; description: string; source: string }>;
  skipped: Array<{ description: string; source: string; reason: string }>;
  replaced: string[];
}

// Topic structure for topic-manager microservice (future)
export interface Topic {
  id: string;
  path: string;
  name: string;
  description: string | null;
  parent_id: string | null;
  children: string[];
  task_count: number;
  created_at: string;
  updated_at: string;
}

export interface TopicTreeNode {
  topic: Topic;
  children: TopicTreeNode[];
}

// Task create/update payloads
export interface CreateTaskPayload {
  description: string;
  assignee?: string | null;
  deadline?: string | null;
  primary_topic?: string;
  secondary_topics?: string[];
  priority?: 'high' | 'medium' | 'low';
  context?: string | null;
  source_transcript_id?: string | null;
  source_transcript_title?: string | null;
}

export interface UpdateTaskPayload {
  description?: string;
  assignee?: string | null;
  deadline?: string | null;
  primary_topic?: string;
  secondary_topics?: string[];
  priority?: 'high' | 'medium' | 'low';
  context?: string | null;
}

// UI state types
export type ViewMode = 'list' | 'kanban' | 'board';
export type GroupBy = 'none' | 'topic' | 'assignee' | 'priority' | 'status';
export type SortBy = 'deadline' | 'priority' | 'created' | 'updated' | 'topic';

export interface FilterState {
  status: string | null;
  topic: string | null;
  assignee: string | null;
  priority: string | null;
  search: string;
}

export interface TopicNode {
  name: string;
  fullPath: string;
  tasks: Task[];
  children: Record<string, TopicNode>;
  taskCount: number;
}
