-- Migration: Add strategy_name column to signals table
-- This column tracks which strategy algorithm generated each signal
-- Nullable to maintain backward compatibility with existing rows

ALTER TABLE signals ADD COLUMN strategy_name VARCHAR(50) NULL;
