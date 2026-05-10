-- Migration: Add actual entry date to watchlist
-- Date: 2026-05-10
-- Description: Stores the user's real buy date for exit-plan calculations.

ALTER TABLE watchlist ADD COLUMN entry_date DATE;
