-- Add steps_completed column to tasks table for checkpoint/resume support
-- Created: 2026-05-06
-- Description: Adds JSON column to track completion status of each step in full update

ALTER TABLE tasks ADD COLUMN IF NOT EXISTS steps_completed JSONB DEFAULT '{}'::jsonb;

-- Create index for faster queries on completed steps
CREATE INDEX IF NOT EXISTS idx_tasks_steps_completed ON tasks USING gin(steps_completed);

-- Add comment
COMMENT ON COLUMN tasks.steps_completed IS 'Step completion status for checkpoint/resume: {"resetting": true, "fetch_data": false, ...}';
