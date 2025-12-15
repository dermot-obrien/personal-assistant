import { useState, useMemo } from 'react';
import { ChevronRight, ChevronDown, FolderOpen, Folder, FileText } from 'lucide-react';
import { clsx } from 'clsx';
import type { Task, TopicNode } from '@/types';

interface TopicTreeProps {
  tasks: Task[];
  onTopicSelect: (topic: string) => void;
  selectedTopic?: string | null;
}

function buildTopicTree(tasks: Task[]): TopicNode {
  const root: TopicNode = {
    name: 'All Topics',
    fullPath: '',
    tasks: [],
    children: {},
    taskCount: tasks.length,
  };

  for (const task of tasks) {
    const parts = task.primary_topic.split('/');
    let current = root;

    for (let i = 0; i < parts.length; i++) {
      const part = parts[i];
      const fullPath = parts.slice(0, i + 1).join('/');

      if (!current.children[part]) {
        current.children[part] = {
          name: part,
          fullPath,
          tasks: [],
          children: {},
          taskCount: 0,
        };
      }

      current = current.children[part];
      current.taskCount++;

      if (i === parts.length - 1) {
        current.tasks.push(task);
      }
    }
  }

  return root;
}

interface TreeNodeProps {
  node: TopicNode;
  level: number;
  onSelect: (topic: string) => void;
  selectedTopic?: string | null;
}

function TreeNode({ node, level, onSelect, selectedTopic }: TreeNodeProps) {
  const [isExpanded, setIsExpanded] = useState(level < 2);
  const hasChildren = Object.keys(node.children).length > 0;
  const isSelected = selectedTopic === node.fullPath;

  return (
    <div>
      <div
        className={clsx(
          'flex items-center gap-2 px-2 py-1.5 rounded-lg cursor-pointer transition-colors',
          isSelected
            ? 'bg-primary-100 text-primary-900'
            : 'hover:bg-gray-100'
        )}
        style={{ paddingLeft: `${level * 16 + 8}px` }}
        onClick={() => {
          if (hasChildren) {
            setIsExpanded(!isExpanded);
          }
          onSelect(node.fullPath);
        }}
      >
        {hasChildren ? (
          <button
            onClick={(e) => {
              e.stopPropagation();
              setIsExpanded(!isExpanded);
            }}
            className="p-0.5 hover:bg-gray-200 rounded"
          >
            {isExpanded ? (
              <ChevronDown className="w-4 h-4 text-gray-500" />
            ) : (
              <ChevronRight className="w-4 h-4 text-gray-500" />
            )}
          </button>
        ) : (
          <span className="w-5" />
        )}

        {hasChildren ? (
          isExpanded ? (
            <FolderOpen className="w-4 h-4 text-primary-500" />
          ) : (
            <Folder className="w-4 h-4 text-primary-500" />
          )
        ) : (
          <FileText className="w-4 h-4 text-gray-400" />
        )}

        <span className="flex-1 text-sm font-medium truncate">{node.name}</span>

        <span className="px-1.5 py-0.5 bg-gray-100 text-gray-600 rounded text-xs font-medium">
          {node.taskCount}
        </span>
      </div>

      {isExpanded && hasChildren && (
        <div>
          {Object.values(node.children)
            .sort((a, b) => a.name.localeCompare(b.name))
            .map((child) => (
              <TreeNode
                key={child.fullPath}
                node={child}
                level={level + 1}
                onSelect={onSelect}
                selectedTopic={selectedTopic}
              />
            ))}
        </div>
      )}
    </div>
  );
}

export function TopicTree({ tasks, onTopicSelect, selectedTopic }: TopicTreeProps) {
  const tree = useMemo(() => buildTopicTree(tasks), [tasks]);

  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
      <div className="p-3 border-b border-gray-200 bg-gray-50">
        <h3 className="font-semibold text-gray-900">Topic Hierarchy</h3>
        <p className="text-xs text-gray-500 mt-0.5">
          {Object.keys(tree.children).length} top-level topics
        </p>
      </div>

      <div className="p-2 max-h-[500px] overflow-y-auto">
        {/* All Tasks option */}
        <div
          className={clsx(
            'flex items-center gap-2 px-2 py-1.5 rounded-lg cursor-pointer transition-colors mb-2',
            !selectedTopic
              ? 'bg-primary-100 text-primary-900'
              : 'hover:bg-gray-100'
          )}
          onClick={() => onTopicSelect('')}
        >
          <span className="w-5" />
          <FolderOpen className="w-4 h-4 text-primary-500" />
          <span className="flex-1 text-sm font-medium">All Topics</span>
          <span className="px-1.5 py-0.5 bg-gray-100 text-gray-600 rounded text-xs font-medium">
            {tree.taskCount}
          </span>
        </div>

        <div className="border-t border-gray-100 pt-2">
          {Object.values(tree.children)
            .sort((a, b) => a.name.localeCompare(b.name))
            .map((child) => (
              <TreeNode
                key={child.fullPath}
                node={child}
                level={0}
                onSelect={onTopicSelect}
                selectedTopic={selectedTopic}
              />
            ))}
        </div>
      </div>
    </div>
  );
}
