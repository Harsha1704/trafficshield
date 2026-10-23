import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import React from 'react';
import { SeverityBadge, StatusBadge, Badge } from '../components/common/Badge';
import { Button } from '../components/common/Button';
import { Card } from '../components/common/Card';
import { EmptyState } from '../components/common/EmptyState';

describe('Common SOC Design System Components', () => {
  it('renders SeverityBadge with accessible contrast and correct casing', () => {
    const { rerender } = render(<SeverityBadge severity="CRITICAL" />);
    expect(screen.getByText('CRITICAL')).toBeDefined();

    rerender(<SeverityBadge severity="LOW" />);
    expect(screen.getByText('LOW')).toBeDefined();
  });

  it('renders StatusBadge with formatted text for false positive', () => {
    render(<StatusBadge status="FALSE_POSITIVE" />);
    expect(screen.getByText('FALSE POSITIVE')).toBeDefined();
  });

  it('renders Button with variants and handles loading state', () => {
    const { rerender } = render(<Button variant="primary">Execute Scoring</Button>);
    expect(screen.getByRole('button')).toBeDefined();
    expect(screen.getByText('Execute Scoring')).toBeDefined();

    rerender(<Button loading>Execute Scoring</Button>);
    expect(screen.getByRole('button').hasAttribute('disabled')).toBe(true);
  });

  it('renders Card with header, badge, and body', () => {
    render(
      <Card title="Feature Contract" badge={<Badge variant="cyan">PASS</Badge>}>
        <div>Card Content Body</div>
      </Card>
    );

    expect(screen.getByText('Feature Contract')).toBeDefined();
    expect(screen.getByText('PASS')).toBeDefined();
    expect(screen.getByText('Card Content Body')).toBeDefined();
  });

  it('renders EmptyState with action button', () => {
    render(
      <EmptyState
        title="No Stored Alerts"
        description="Run batch scoring to view alerts."
        action={<button>Seed Sample Alerts</button>}
      />
    );

    expect(screen.getByText('No Stored Alerts')).toBeDefined();
    expect(screen.getByText('Seed Sample Alerts')).toBeDefined();
  });
});
