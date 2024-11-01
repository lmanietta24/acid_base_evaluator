import os
from flask import Flask, render_template, request, redirect, url_for, flash
from tabulate import tabulate

app = Flask(__name__)

# Securely set the secret key using environment variables
app.secret_key = os.environ.get('SECRET_KEY', 'your_default_secret_key')  # Replace with a secure key in production

def assess_pH(pH):
    """Assess the pH status."""
    if pH > 7.4:
        return 'Alkalemic'
    elif pH < 7.4:
        return 'Acidemic'
    else:
        return 'Normal'

def determine_primary_disorder(data, pH_status):
    """Determine the primary acid-base disorder."""
    disorders = []
    
    # Assess Respiratory Disorders
    if data['PaCO2'] > 40:
        disorders.append('Respiratory Acidosis')
    elif data['PaCO2'] < 40:
        disorders.append('Respiratory Alkalosis')
    
    # Assess Metabolic Disorders
    if data['HCO3'] > 26:
        disorders.append('Metabolic Alkalosis')
    elif data['HCO3'] < 22:
        disorders.append('Metabolic Acidosis')
    
    # Determine if mixed disorder
    if len(disorders) > 1:
        return disorders, True  # Mixed disorder
    else:
        return disorders, False  # Single primary disorder

def assess_compensation(data, primary_disorder):
    """Assess the compensation mechanism."""
    compensation = {}
    if primary_disorder == 'Respiratory Acidosis':
        # Determine Acute or Chronic based on [HCO3-] levels
        if data['HCO3'] > 24:
            compensation['Type'] = 'Chronic Respiratory Acidosis'
            compensation_change = 0.003  # pH change per mmHg PaCO2
            expected_pH_change = (data['PaCO2'] - 40) * compensation_change
            pH_expected = 7.4 - expected_pH_change
        else:
            compensation['Type'] = 'Acute Respiratory Acidosis'
            compensation_change = 0.008  # pH change per mmHg PaCO2
            expected_pH_change = (data['PaCO2'] - 40) * compensation_change
            pH_expected = 7.4 - expected_pH_change
        
        compensation['Expected pH'] = round(pH_expected, 3)
        return compensation

    elif primary_disorder == 'Respiratory Alkalosis':
        # Determine Acute or Chronic based on [HCO3-] levels
        if data['HCO3'] < 22:
            compensation['Type'] = 'Chronic Respiratory Alkalosis'
            compensation_change = -0.003  # pH change per mmHg PaCO2
            expected_pH_change = (40 - data['PaCO2']) * compensation_change
            pH_expected = 7.4 + expected_pH_change
        else:
            compensation['Type'] = 'Acute Respiratory Alkalosis'
            compensation_change = 0.008  # pH change per mmHg PaCO2
            expected_pH_change = (40 - data['PaCO2']) * compensation_change
            pH_expected = 7.4 + expected_pH_change
        
        compensation['Expected pH'] = round(pH_expected, 3)
        return compensation

    elif primary_disorder == 'Metabolic Acidosis':
        # Calculate Expected PaCO2
        Delta_HCO3 = 24 - data['HCO3']
        expected_PaCO2 = 1.2 * Delta_HCO3 + 40
        compensation['Expected PaCO2'] = round(expected_PaCO2, 1)
        return compensation

    elif primary_disorder == 'Metabolic Alkalosis':
        # Calculate Expected PaCO2
        Delta_HCO3 = data['HCO3'] - 24
        expected_PaCO2 = 0.7 * Delta_HCO3 + 40
        compensation['Expected PaCO2'] = round(expected_PaCO2, 1)
        return compensation

    else:
        return compensation

def calculate_anion_gap(data):
    """Calculate the Anion Gap and related metrics."""
    AG = data['Na'] - (data['Cl'] + data['HCO3'])
    # Correct for albumin if needed
    if data['albumin'] < 4:
        AG_corrected = AG + (2.5 * (4 - data['albumin']))
    else:
        AG_corrected = AG
    DAG = AG_corrected - 12
    return {
        'AG': round(AG, 1),
        'AG_corrected': round(AG_corrected, 1),
        'DAG': round(DAG, 1)
    }

def identify_mixed_disorder(data, primary_disorders, is_mixed):
    """Identify mixed acid-base disorders."""
    mixed = {}
    # Identify the primary disorder based on the degree of pH deviation
    # For simplicity, assume Metabolic disorder has a greater effect on pH than Respiratory
    if 'Metabolic Acidosis' in primary_disorders and 'Respiratory Alkalosis' in primary_disorders:
        # Calculate the contribution to pH
        delta_pH_acidosis = (24 - data['HCO3']) * 0.015
        delta_pH_alkalosis = (40 - data['PaCO2']) * 0.008
        net_pH_change = delta_pH_acidosis + delta_pH_alkalosis
        net_pH = 7.4 - net_pH_change  # Starting from normal pH
        
        if net_pH < 7.35:
            primary = 'Metabolic Acidosis'
            concomitant = 'Respiratory Alkalosis'
        elif net_pH > 7.45:
            primary = 'Respiratory Alkalosis'
            concomitant = 'Metabolic Acidosis'
        else:
            primary = 'Both Disorders Equally Contribute'
            concomitant = 'None'
        
        mixed['Primary Disorder'] = primary
        mixed['Concomitant Disorder'] = concomitant

    elif 'Metabolic Alkalosis' in primary_disorders and 'Respiratory Acidosis' in primary_disorders:
        # Similar logic as above
        delta_pH_alkalosis = (data['HCO3'] - 24) * 0.015  # Metabolic Alkalosis: each 1 mEq/L increase in HCO3- increases pH by ~0.015
        delta_pH_acidosis = (data['PaCO2'] - 40) * 0.008  # Respiratory Acidosis: each 1 mmHg increase in PaCO2 decreases pH by ~0.008
        net_pH_change = delta_pH_alkalosis - delta_pH_acidosis
        net_pH = 7.4 + net_pH_change  # Starting from normal pH
        
        if net_pH > 7.45:
            primary = 'Metabolic Alkalosis'
            concomitant = 'Respiratory Acidosis'
        elif net_pH < 7.35:
            primary = 'Respiratory Acidosis'
            concomitant = 'Metabolic Alkalosis'
        else:
            primary = 'Both Disorders Equally Contribute'
            concomitant = 'None'
        
        mixed['Primary Disorder'] = primary
        mixed['Concomitant Disorder'] = concomitant

    else:
        # Handle other mixed scenarios if needed
        mixed['Primary Disorder'] = 'Complex Mixed Disorder'
        mixed['Concomitant Disorder'] = 'Requires Clinical Correlation'
    
    return mixed

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        try:
            # Retrieve and convert form data to floats
            Na = float(request.form['Na'])
            K = float(request.form['K'])
            Cl = float(request.form['Cl'])
            HCO3_bmp = float(request.form['HCO3_bmp'])
            albumin = float(request.form['albumin'])
            pH = float(request.form['pH'])
            PaCO2 = float(request.form['PaCO2'])
            PaO2 = float(request.form['PaO2'])
            HCO3_abg = float(request.form['HCO3_abg'])
            
            # Check consistency of [HCO3-] between BMP and ABG
            if abs(HCO3_bmp - HCO3_abg) > 3:
                flash("[HCO3-] values from BMP and ABG differ by more than 3 mEq/L. Results may be uninterpretable.")
                return redirect(url_for('index'))
            else:
                HCO3 = (HCO3_bmp + HCO3_abg) / 2  # Average if within range
            
            # Validate normal ranges for inputs (basic validation)
            warnings = []
            if not (7.35 <= pH <= 7.45):
                warnings.append("pH is outside the normal range (7.35-7.45).")
            
            if not (38 <= PaCO2 <= 42):
                warnings.append("PaCO2 is outside the normal range (38-42 mmHg).")
            
            if not (22 <= HCO3 <= 26):
                warnings.append("[HCO3-] is outside the normal range (22-26 mEq/L).")
            
            # Compile data into a dictionary
            data = {
                'Na': Na,
                'K': K,
                'Cl': Cl,
                'HCO3': HCO3,
                'albumin': albumin,
                'pH': pH,
                'PaCO2': PaCO2,
                'PaO2': PaO2
            }
            
            # Assess pH
            pH_status = assess_pH(data['pH'])
            
            # Determine primary disorder
            disorders, is_mixed = determine_primary_disorder(data, pH_status)
            
            # Assess compensation
            compensation = {}
            if 'Respiratory Acidosis' in disorders or 'Respiratory Alkalosis' in disorders:
                primary_resp = 'Respiratory Acidosis' if 'Respiratory Acidosis' in disorders else 'Respiratory Alkalosis'
                compensation = assess_compensation(data, primary_resp)
            
            # Calculate Anion Gap
            AG_info = {}
            if 'Metabolic Acidosis' in disorders or 'Metabolic Alkalosis' in disorders:
                AG_info = calculate_anion_gap(data)
            
            # Identify mixed disorder
            mixed_disorder = {}
            if is_mixed:
                mixed_disorder = identify_mixed_disorder(data, disorders, is_mixed)
            else:
                if 'Metabolic Acidosis' in disorders or 'Metabolic Alkalosis' in disorders:
                    mixed_disorder = identify_mixed_disorder(data, disorders, is_mixed)
                elif 'Respiratory Acidosis' in disorders or 'Respiratory Alkalosis' in disorders:
                    mixed_disorder = identify_mixed_disorder(data, disorders, is_mixed)
            
            # Compile diagnosis
            diagnosis = []
            if is_mixed:
                diagnosis.append("Mixed Acid-Base Disorder")
                if mixed_disorder.get('Primary Disorder') != 'Both Disorders Equally Contribute':
                    diagnosis.append(mixed_disorder.get('Primary Disorder'))
                    diagnosis.append(mixed_disorder.get('Concomitant Disorder'))
            else:
                if disorders:
                    diagnosis.append(disorders[0])
                if mixed_disorder.get('Concomitant Disorder') and mixed_disorder.get('Concomitant Disorder') not in ['No Concomitant Respiratory Disorder', 'No Concomitant Metabolic Disorder', 'N/A']:
                    diagnosis.append(mixed_disorder.get('Concomitant Disorder'))
            
            # Create summary table using tabulate
            table = [
                ['pH', data['pH'], pH_status],
                ['PaCO2', data['PaCO2'], f"{data['PaCO2']} mmHg"],
                ['[HCO3-]', data['HCO3'], f"{data['HCO3']} mEq/L"],
                ['[Na+]', data['Na'], f"{data['Na']} mEq/L"],
                ['[Cl-]', data['Cl'], f"{data['Cl']} mEq/L"],
                ['Albumin', data['albumin'], f"{data['albumin']} g/dL"],
                ['Anion Gap', AG_info.get('AG', 'N/A'), f"{AG_info.get('AG')} mEq/L"],
                ['AG Corrected', AG_info.get('AG_corrected', 'N/A'), f"{AG_info.get('AG_corrected')} mEq/L"],
                ['Excess AG (DAG)', AG_info.get('DAG', 'N/A'), f"{AG_info.get('DAG')} mEq/L"]
            ]
            summary = tabulate(table, headers=['Parameter', 'Value', 'Interpretation'], tablefmt='grid')
            
            # Render the result template with all calculated data
            return render_template('result.html',
                                   warnings=warnings,
                                   pH_status=pH_status,
                                   disorders=disorders,
                                   is_mixed=is_mixed,
                                   compensation=compensation,
                                   AG_info=AG_info,
                                   mixed_disorder=mixed_disorder,
                                   diagnosis=diagnosis,
                                   summary=summary)
        
        except ValueError:
            # Flash a message if non-numeric input is detected
            flash("Please enter valid numeric values for all fields.")
            return redirect(url_for('index'))
    
    # For GET requests, render the input form
    return render_template('index.html')

# Custom error handler for 500 Internal Server Error
@app.errorhandler(500)
def internal_server_error(e):
    return render_template('500.html'), 500

if __name__ == "__main__":
    # Get the port from environment variables (required by Heroku)
    port = int(os.environ.get("PORT", 5000))
    # Run the Flask application
    app.run(host='0.0.0.0', port=port, debug=True)
