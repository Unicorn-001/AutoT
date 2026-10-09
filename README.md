# AutoT

## Local web scanner

From the project root, activate the existing virtual environment and install dependencies:

```sh
source venv/bin/activate
python -m pip install -r requirements.txt
python -m streamlit run web_app.py
```

The web scanner uses defaults from `data_storage/config/app_settings.csv`.
Choose a universe CSV containing a `symbol` column, period, interval and shortlist size,
then select **Run Scan**. Results remain in the current browser session until the next scan.
Ranked results, the top shortlist and trade opportunities come from the shared scanner service.
The web app does not execute trades or write CLI reports. The CLI remains available with
`python main.py`.
