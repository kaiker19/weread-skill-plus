#!/bin/bash
set -e
echo "🔄 同步官方 weread-skills..."
npx skills update -y
if git diff --quiet skills-lock.json; then
  echo "✅ 已是最新，无需更新"
else
  echo "📦 检测到更新，skills-lock.json 已变更"
  git diff skills-lock.json
fi
