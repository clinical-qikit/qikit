import React, { useState } from 'react';
import { 
  TabList, Tab, makeStyles, tokens 
} from '@fluentui/react-components';
import { SpcWizard } from './spc/SpcWizard';
import { DoeWizard } from './doe/DoeWizard';

const useStyles = makeStyles({
  container: {
    display: 'flex',
    flexDirection: 'column',
    height: '100%',
  },
  content: {
    flex: 1,
    overflowY: 'auto',
  }
});

export const App: React.FC = () => {
  const styles = useStyles();
  const [selectedTab, setSelectedTab] = useState<'spc' | 'doe'>('spc');

  return (
    <div className={styles.container}>
      <TabList 
        selectedValue={selectedTab} 
        onTabSelect={(_, data) => setSelectedTab(data.value as 'spc' | 'doe')}
      >
        <Tab value="spc">SPC</Tab>
        <Tab value="doe">DOE</Tab>
      </TabList>
      <div className={styles.content}>
        {selectedTab === 'spc' ? <SpcWizard /> : <DoeWizard />}
      </div>
    </div>
  );
};
