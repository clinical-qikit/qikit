import React from 'react';
import { Button, Tooltip } from '@fluentui/react-components';
import { QuestionCircle16Regular } from '@fluentui/react-icons';

interface TooltipHelpProps {
  content: string;
  relationship?: 'description' | 'label' | 'inaccessible';
}

export const TooltipHelp: React.FC<TooltipHelpProps> = ({ content, relationship = 'description' }) => {
  return (
    <Tooltip content={content} relationship={relationship}>
      <Button
        appearance="transparent"
        icon={<QuestionCircle16Regular />}
        size="small"
        style={{ minWidth: 'auto', padding: '0 4px' }}
        aria-label="Help"
      />
    </Tooltip>
  );
};
