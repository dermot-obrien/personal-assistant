import { useState } from 'react';
import { TopicTree, TaskList } from '@/components';
import { useTasks } from '@/hooks/useTasks';

export function Topics() {
  const [selectedTopic, setSelectedTopic] = useState<string | null>(null);

  // Fetch all tasks for topic tree
  const { data: allTasksData, isLoading: allLoading } = useTasks({
    status: null,
    topic: null,
    assignee: null,
    priority: null,
    search: '',
  });

  // Fetch filtered tasks when topic is selected
  const { data: filteredData, isLoading: filteredLoading } = useTasks({
    status: null,
    topic: selectedTopic,
    assignee: null,
    priority: null,
    search: '',
  });

  const tasks = selectedTopic ? (filteredData?.tasks || []) : (allTasksData?.tasks || []);
  const isLoading = allLoading || (selectedTopic && filteredLoading);

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="bg-white border-b border-gray-200 px-6 py-4">
        <h1 className="text-xl font-bold text-gray-900">Topics</h1>
        <p className="text-sm text-gray-500 mt-0.5">
          Browse tasks organized by hierarchical topics
        </p>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-hidden flex">
        {/* Sidebar - Topic Tree */}
        <div className="w-80 border-r border-gray-200 overflow-y-auto p-4 bg-gray-50">
          {allLoading ? (
            <div className="animate-pulse space-y-2">
              {[1, 2, 3, 4, 5].map(i => (
                <div key={i} className="h-8 bg-gray-200 rounded" />
              ))}
            </div>
          ) : (
            <TopicTree
              tasks={allTasksData?.tasks || []}
              onTopicSelect={(topic) => setSelectedTopic(topic || null)}
              selectedTopic={selectedTopic}
            />
          )}
        </div>

        {/* Main - Task List */}
        <div className="flex-1 overflow-y-auto p-6">
          <div className="mb-4">
            <h2 className="text-lg font-semibold text-gray-900">
              {selectedTopic || 'All Topics'}
            </h2>
            <p className="text-sm text-gray-500">
              {tasks.length} task{tasks.length !== 1 ? 's' : ''}
            </p>
          </div>

          <TaskList
            tasks={tasks}
            isLoading={!!isLoading}
          />
        </div>
      </div>
    </div>
  );
}
