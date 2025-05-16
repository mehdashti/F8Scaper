// App.js
import React, { useState } from 'react';
import axios from 'axios';
import './styles/App.css';

function App() {
  const [url, setUrl] = useState('');
  const [aggregatedSelectableItemsList, setAggregatedSelectableItemsList] = useState([]);
  const [selectedItems, setSelectedItems] = useState([]);
  const [extractedData, setExtractedData] = useState({});
  const [channelSpecificInfo, setChannelSpecificInfo] = useState({});

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [globalStatusMessage, setGlobalStatusMessage] = useState(null);
  const [currentStep, setCurrentStep] = useState(1);

  const handleRender = async () => {
    setLoading(true);
    setError(null);
    setGlobalStatusMessage(null);
    setAggregatedSelectableItemsList([]);
    setSelectedItems([]);
    setExtractedData({});
    setChannelSpecificInfo({});
    setCurrentStep(1);

    try {
      const response = await axios.post('http://localhost:5000/render', { url });
      const responseData = response.data;

      if (responseData.error) {
        setError(responseData.error);
      } else {
        setChannelSpecificInfo(responseData.channel_specific_info || {});
        setAggregatedSelectableItemsList(responseData.aggregated_selectable_items || []);

        if (responseData.aggregated_selectable_items && responseData.aggregated_selectable_items.length > 0) {
          setCurrentStep(2); 
        } else {
          setGlobalStatusMessage(responseData.global_status_message || "No selectable items found or page content issue.");
          const channelErrors = Object.values(responseData.channel_specific_info || {})
                                   .map(info => info.parsing_error)
                                   .filter(Boolean);
          if (channelErrors.length > 0 && !responseData.global_status_message) {
            setError("Issues found: " + channelErrors.join("; "));
          }
        }
      }
    } catch (err) {
      setError('Error fetching page info. Please check the URL and backend server.');
      console.error('Error rendering page:', err);
    }
    setLoading(false);
  };

  const handleItemSelectionChange = (selectedOptionsFromEvent) => {
    const newSelectedItems = selectedOptionsFromEvent.map(optionValue => JSON.parse(optionValue));
    setSelectedItems(newSelectedItems);
  };

  const handleExtract = async () => {
    if (selectedItems.length === 0) {
      setError("Please select at least one item to extract data.");
      return;
    }
    setLoading(true);
    setError(null);
    setGlobalStatusMessage(null);

    try {
      const payload = {
        url,
        selected_items: selectedItems.map(item => ({
          channel_name: item.channel_name,
          actual_selector: item.actual_selector
        }))
      };
      const response = await axios.post('http://localhost:5000/render', payload);
      const responseData = response.data;

      if (responseData.error) {
        setError(responseData.error);
      } else {
        setExtractedData(responseData.channels_data_parsed || {});
        setChannelSpecificInfo(responseData.channel_specific_info || {}); 
        setAggregatedSelectableItemsList(responseData.aggregated_selectable_items || []);


        if (responseData.channels_data_parsed && Object.keys(responseData.channels_data_parsed).length > 0) {
          setCurrentStep(3); 
        } else {
           setGlobalStatusMessage(responseData.global_status_message || "No data extracted for the selected items. Please check your selections or the page content.");
           setCurrentStep(2);
        }
      }
    } catch (err) {
      setError('Error extracting data. Please try again.');
      console.error('Error extracting data:', err);
    }
    setLoading(false);
  };

  const handleSave = async () => {
    try {
      await axios.post('http://localhost:5000/save-data', {
        url,
        currency_data: extractedData
      });
      alert('Currency data configuration saved successfully!');
    } catch (err) {
      console.error('Error saving data:', err);
      alert('Failed to save data configuration.');
    }
  };

  const getHeadersForTable = (tableRows) => {
    if (!tableRows || tableRows.length === 0) return [];
    return Object.keys(tableRows[0]);
  };

  const canExtract = selectedItems.length > 0;

  return (
    <div className="App">
      <h1>Currency Rate Extractor</h1>

      {/* Step 1: Enter URL and Fetch Page Info */}
      {currentStep >= 1 && (
        <div className="step-container">
          <h2>Step 1: Fetch Page Information</h2>
          <input
            type="text"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="Enter URL"
            disabled={loading}
          />
          <button onClick={handleRender} disabled={loading || !url}>
            {loading && currentStep === 1 ? 'Loading...' : 'Fetch Page Info'}
          </button>
        </div>
      )}

      {error && <p className="error">{error}</p>}
      {globalStatusMessage && <p className="info">{globalStatusMessage}</p>}


      {/* Step 2: Select Items to Extract */}
      {currentStep === 2 && aggregatedSelectableItemsList.length > 0 && (
        <div className="step-container selectable-tags-container">
          <h2>Step 2: Select Items to Extract</h2>
          <div className="channel-tag-selection">
            <h3>Available Items (from all channels):</h3>
            <select
              multiple

              value={selectedItems.map(item => JSON.stringify(item))}
              onChange={(e) => handleItemSelectionChange(Array.from(e.target.selectedOptions, option => option.value))}
              size={Math.min(aggregatedSelectableItemsList.length, 10)} 
              style={{ width: '100%', minHeight: '150px',  overflowY: 'auto' }}
            >
              {aggregatedSelectableItemsList.map((item, index) => (

                <option key={`${item.channel_name}-${item.actual_selector}-${index}`} value={JSON.stringify(item)}>
                  {item.display_text} 
                </option>
              ))}
            </select>
          </div>
          <button onClick={handleExtract} disabled={loading || !canExtract}>
            {loading ? 'Extracting...' : 'Extract Data from Selected Items'}
          </button>
        </div>
      )}

      {/* Step 3: Display Extracted Data */}
      {currentStep === 3 && Object.keys(extractedData).length > 0 && (
        <div className="step-container currency-data-container">
          <h2>Step 3: Extracted Data</h2>
          {Object.entries(extractedData).map(([channelName, selectorsData]) => (
            <div key={channelName} className="channel-data">
              <h3>
                Channel: {channelName}
                {channelSpecificInfo[channelName]?.page_title && ` (${channelSpecificInfo[channelName].page_title})`}
              </h3>
              {channelSpecificInfo[channelName]?.parsing_error && (
                <p className="error">Note for this channel: {channelSpecificInfo[channelName].parsing_error}</p>
              )}

              {Object.keys(selectorsData).length === 0 && !channelSpecificInfo[channelName]?.parsing_error && (
                 <p>No data extracted for this channel with the selected items, or no items were selected for this channel.</p>
              )}

              {Object.entries(selectorsData).map(([selector, tableRows]) => {
                if (!tableRows || tableRows.length === 0) {
                  return <p key={selector}>No data found for item (Selector: <code>{selector}</code>)</p>;
                }
                const headers = getHeadersForTable(tableRows);
                return (
                  <div key={selector} className="table-data">
                    <h4>Table (Selector: <code>{selector}</code>)</h4>
                    <table>
                      <thead>
                        <tr>
                          {headers.map(header => (
                            <th key={header}>{header.replace(/_/g, ' ').toUpperCase()}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {tableRows.map((row, rowIndex) => (
                          <tr key={rowIndex}>
                            {headers.map(header => (
                              <td key={`${rowIndex}-${header}`}>{row[header] === undefined || row[header] === null ? 'N/A' : String(row[header])}</td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                );
              })}
            </div>
          ))}
          <button onClick={handleSave} disabled={loading}>
            Save Extracted Data Configuration
          </button>
        </div>
      )}
      {currentStep === 3 && Object.keys(extractedData).length === 0 && globalStatusMessage && (
          <p className="info">{globalStatusMessage}</p>
      )}
    </div>
  );
}

export default App;