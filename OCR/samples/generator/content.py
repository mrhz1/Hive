"""Synthetic clinical content for OCR / de-identification test corpora.

Everything here is fabricated. Names, MRNs, SSNs, addresses, phone numbers,
insurance IDs and NPIs are invented for the purpose of testing PHI recall and
are not associated with any real person, provider or facility.

Two documents are described:

  PRINTED  - a modern, typeset inpatient record for GRACE ELEANOR WHITFIELD
  HANDWRITTEN - an old, hand-kept ward chart for ARTHUR LEONARD BRENNAN

Each is exactly 20 pages. Page content is expressed as blocks that the
renderers lay out; the same blocks produce the ground-truth text files.
"""

# --------------------------------------------------------------------------
# PHI inventory - used to build the ground-truth entity list
# --------------------------------------------------------------------------

PRINTED_PHI = {
    "PATIENT": ["Grace Eleanor Whitfield", "Whitfield, Grace E.", "Grace E. Whitfield",
                "Gracie Whitfield"],
    "MRN": ["MRN 40-77-1592", "40-77-1592"],
    "SSN": ["512-84-9037"],
    "DOB": ["03/14/1951"],
    "ACCOUNT": ["ACCT 8891274430"],
    "ADDRESS": ["1427 Birchwood Terrace, Apt 3B, Cedar Falls, IA 50613"],
    "PHONE": ["(319) 555-0148", "(319) 555-0192", "(563) 555-0771"],
    "EMAIL": ["g.whitfield51@mailhaven.example.com"],
    "INSURANCE": ["Meridian Blue PPO, Policy MBP-448120977, Group 30514"],
    "EMPLOYER": ["Cedar Falls Public Library"],
    "CONTACT": ["Daniel R. Whitfield (son)", "Priscilla Vance (sister)"],
    "PROVIDER": [
        "Harold T. Nakamura, MD", "Yvette Okonkwo, MD", "Steven Kaufmann, MD",
        "Rosalind Achebe, MD", "Peter Vandermolen, DO", "Ingrid Solberg, MD",
        "Marcus Delacroix, MD", "Bethany Ruiz-Alvarado, PA-C", "Tomasz Wieczorek, MD",
        "Karen Fitzsimmons, RN", "Oluwaseun Adeyemi, PharmD", "Lucille Marchetti, RN",
        "Devendra Ramaswamy, MD", "Colette Beauchamp, MD", "Ahmad Farhadi, MD",
    ],
    "FACILITY": [
        "Saint Bartholomew Regional Medical Center", "Cedar Falls Family Practice",
        "Blackhawk County Imaging Associates", "Willow Creek Skilled Nursing Facility",
    ],
    "NPI": ["1487302956", "1629480371"],
    "DATE": ["April 6, 2018", "04/06/2018", "04/07/2018", "04/08/2018", "04/09/2018",
             "04/10/2018", "04/11/2018", "04/12/2018", "04/13/2018", "April 13, 2018"],
}

HANDWRITTEN_PHI = {
    "PATIENT": ["Arthur Leonard Brennan", "Brennan, Arthur L.", "Mr. Brennan", "Art Brennan"],
    "MRN": ["Unit No. 22-84-016", "22-84-016"],
    "SSN": ["327-56-4188"],
    "DOB": ["11 Sept 1919", "9/11/19"],
    "ADDRESS": ["58 Marlborough Row, Fall River, Mass. 02720"],
    "PHONE": ["OS 4-7719", "(617) 555-0233"],
    "CONTACT": ["Mrs. Edith Brennan (wife)", "Fr. Cornelius Doyle"],
    "PROVIDER": [
        "R. W. Ashcroft, M.D.", "J. P. Mulcahy, M.D.", "H. Steinmetz, M.D.",
        "L. Cavanaugh, M.D.", "Sr. M. Bernadette, R.N.", "T. Okamura, M.D.",
        "E. Vasquez, R.N.", "G. Pemberton, M.D.", "D. Lindqvist, M.D.",
        "A. Chowdhury, M.D.", "Miss K. Halloran, R.N.",
    ],
    "FACILITY": ["Providence Mercy Hospital", "Ward C - Men's Medical",
                 "St. Anne's Convalescent Home"],
    "DATE": ["17 Jan 1971", "18 Jan 1971", "19 Jan 1971", "20 Jan 1971", "21 Jan 1971",
             "22 Jan 1971", "23 Jan 1971", "24 Jan 1971", "26 Jan 1971", "29 Jan 1971",
             "2 Feb 1971"],
}


# --------------------------------------------------------------------------
# PRINTED DOCUMENT - 20 typeset pages
# --------------------------------------------------------------------------

PRINTED_HEADER = ("Saint Bartholomew Regional Medical Center",
                  "Whitfield, Grace E.  •  MRN 40-77-1592  •  DOB 03/14/1951")


def printed_pages():
    """Return a list of 20 pages; each page is a list of layout blocks."""
    P = []

    # ---- 1. Face sheet -------------------------------------------------
    P.append([
        ("h1", "PATIENT FACE SHEET / REGISTRATION RECORD"),
        ("rule",),
        ("kv2", [("Patient Name", "Whitfield, Grace Eleanor"),
                 ("Medical Record No.", "40-77-1592"),
                 ("Also Known As", "Gracie Whitfield"),
                 ("Account Number", "8891274430"),
                 ("Date of Birth", "03/14/1951"),
                 ("Age / Sex", "67 y / Female"),
                 ("Social Security No.", "512-84-9037"),
                 ("Marital Status", "Widowed"),
                 ("Race / Ethnicity", "White, Non-Hispanic"),
                 ("Preferred Language", "English"),
                 ("Religion", "Lutheran"),
                 ("Advance Directive", "On file, DPOA-HC")]),
        ("space", 6),
        ("h2", "CONTACT INFORMATION"),
        ("kv2", [("Street Address", "1427 Birchwood Terrace, Apt 3B"),
                 ("City / State / ZIP", "Cedar Falls, IA 50613"),
                 ("County", "Black Hawk"),
                 ("Home Telephone", "(319) 555-0148"),
                 ("Mobile Telephone", "(319) 555-0192"),
                 ("Electronic Mail", "g.whitfield51@mailhaven.example.com"),
                 ("Employer", "Cedar Falls Public Library"),
                 ("Occupation", "Reference Librarian, retired 2016")]),
        ("space", 6),
        ("h2", "EMERGENCY CONTACTS"),
        ("table", ["Name", "Relationship", "Telephone", "Address"],
         [["Daniel R. Whitfield", "Son", "(319) 555-0192",
           "884 Ridgeline Dr, Waterloo, IA 50702"],
          ["Priscilla Vance", "Sister", "(563) 555-0771",
           "12 Quarry Ln, Dubuque, IA 52001"]],
         [130, 90, 100, 190]),
        ("space", 6),
        ("h2", "GUARANTOR AND INSURANCE"),
        ("kv2", [("Guarantor", "Self"),
                 ("Primary Payer", "Meridian Blue PPO"),
                 ("Policy Number", "MBP-448120977"),
                 ("Group Number", "30514"),
                 ("Secondary Payer", "Medicare Part B"),
                 ("Medicare Beneficiary ID", "4QW7-GH2-KL86"),
                 ("Prior Authorization", "PA-2018-77412"),
                 ("Copay Collected", "$250.00")]),
        ("space", 6),
        ("h2", "ENCOUNTER"),
        ("kv2", [("Admission Date/Time", "04/06/2018 14:22"),
                 ("Admission Type", "Emergency, via ED"),
                 ("Attending Physician", "Harold T. Nakamura, MD"),
                 ("Attending NPI", "1487302956"),
                 ("Referring Physician", "Yvette Okonkwo, MD"),
                 ("Referring Practice", "Cedar Falls Family Practice"),
                 ("Admitting Diagnosis", "Community-acquired pneumonia"),
                 ("Nursing Unit / Bed", "5 North, Room 512-A")]),
        ("space", 8),
        ("small", "This document contains protected health information. Unauthorized "
                  "disclosure is prohibited under 45 CFR Parts 160 and 164."),
    ])

    # ---- 2. H&P part 1 -------------------------------------------------
    P.append([
        ("h1", "HISTORY AND PHYSICAL EXAMINATION"),
        ("kv2", [("Date of Service", "April 6, 2018"),
                 ("Dictated By", "Harold T. Nakamura, MD"),
                 ("Transcribed", "04/06/2018 19:41"),
                 ("Service", "Internal Medicine")]),
        ("rule",),
        ("h2", "CHIEF COMPLAINT"),
        ("p", "Shortness of breath and productive cough for five days."),
        ("h2", "HISTORY OF PRESENT ILLNESS"),
        ("p", "Grace Eleanor Whitfield is a 67-year-old widowed white female with a "
              "history of chronic obstructive pulmonary disease, type 2 diabetes "
              "mellitus and paroxysmal atrial fibrillation who presents to the "
              "emergency department at Saint Bartholomew Regional Medical Center on "
              "April 6, 2018 with a five-day history of progressive dyspnea and cough "
              "productive of thick yellow-green sputum. The patient states that "
              "symptoms began on or about April 1 with rhinorrhea and low-grade "
              "fever, which she treated at home with acetaminophen and an over-the-"
              "counter antitussive without relief."),
        ("p", "Over the subsequent three days she noted increasing exertional "
              "breathlessness, initially with climbing the single flight of stairs to "
              "her apartment at 1427 Birchwood Terrace and, by the morning of "
              "presentation, with ambulation across a single room. She reports "
              "subjective fevers with rigors on the night of April 5, right-sided "
              "pleuritic chest discomfort rated 6 out of 10, and two episodes of "
              "near-syncope. Her son, Daniel R. Whitfield, contacted the office of "
              "Yvette Okonkwo, MD at Cedar Falls Family Practice, who advised "
              "immediate evaluation."),
        ("p", "She denies hemoptysis, orthopnea, paroxysmal nocturnal dyspnea, lower "
              "extremity edema, recent long-distance travel, sick contacts other than "
              "a grandchild with an upper respiratory infection two weeks prior, or "
              "known tuberculosis exposure. She has not received an influenza "
              "vaccination this season. Pneumococcal vaccination status is unknown to "
              "the patient; records from Cedar Falls Family Practice have been "
              "requested by facsimile to (319) 555-0148."),
        ("h2", "PAST MEDICAL HISTORY"),
        ("bullets", [
            "Chronic obstructive pulmonary disease, GOLD stage II, diagnosed 2009",
            "Type 2 diabetes mellitus, diagnosed 2003, most recent HbA1c 7.8% (01/2018)",
            "Paroxysmal atrial fibrillation, diagnosed 2014, CHA2DS2-VASc score 4",
            "Essential hypertension",
            "Hyperlipidemia",
            "Osteoarthritis, bilateral knees",
            "Diverticulosis, incidental on colonoscopy 2015",
        ]),
        ("h2", "PAST SURGICAL HISTORY"),
        ("bullets", [
            "Cholecystectomy, laparoscopic, 1998, Mercy Medical Center",
            "Total abdominal hysterectomy with bilateral salpingo-oophorectomy, 1994",
            "Cataract extraction with intraocular lens, right eye, 2016",
        ]),
    ])

    # ---- 3. H&P part 2 -------------------------------------------------
    P.append([
        ("h1", "HISTORY AND PHYSICAL EXAMINATION (CONTINUED)"),
        ("h2", "MEDICATIONS PRIOR TO ADMISSION"),
        ("table", ["Medication", "Dose", "Route", "Frequency"],
         [["Tiotropium bromide", "18 mcg", "INH", "Daily"],
          ["Albuterol sulfate HFA", "90 mcg/actuation", "INH", "Q4H PRN"],
          ["Metformin hydrochloride", "1000 mg", "PO", "BID with meals"],
          ["Apixaban", "5 mg", "PO", "BID"],
          ["Metoprolol succinate ER", "50 mg", "PO", "Daily"],
          ["Lisinopril", "20 mg", "PO", "Daily"],
          ["Atorvastatin calcium", "40 mg", "PO", "Nightly"],
          ["Cholecalciferol", "2000 units", "PO", "Daily"]],
         [180, 110, 70, 150]),
        ("h2", "ALLERGIES"),
        ("p", "SULFAMETHOXAZOLE-TRIMETHOPRIM - diffuse morbilliform rash, 1997. "
              "CODEINE - nausea and vomiting, intolerance rather than true allergy. "
              "No known latex or food allergies. Allergy list reconciled with the "
              "patient and with her son by Oluwaseun Adeyemi, PharmD."),
        ("h2", "SOCIAL HISTORY"),
        ("p", "The patient is a widow; her husband died in 2011. She lives alone in a "
              "second-floor apartment and remains independent in all activities of "
              "daily living. She retired in 2016 after thirty-one years as a "
              "reference librarian with the Cedar Falls Public Library. She has a "
              "35-pack-year smoking history, having quit in 2009. She reports two to "
              "three glasses of wine per week and denies illicit substance use. She "
              "drives, and has one indoor cat."),
        ("h2", "FAMILY HISTORY"),
        ("p", "Mother deceased at age 74 of myocardial infarction. Father deceased at "
              "age 81 of complications of prostate carcinoma. One sister, Priscilla "
              "Vance, age 63, living, with hypothyroidism. One son, Daniel R. "
              "Whitfield, age 41, living and well."),
        ("h2", "REVIEW OF SYSTEMS"),
        ("p", "Constitutional: positive for fever, chills, fatigue, anorexia; four "
              "pounds of unintentional weight loss. Eyes: negative. ENT: positive for "
              "sore throat and rhinorrhea. Cardiovascular: positive for palpitations, "
              "negative for chest pressure at rest. Respiratory: as in the history of "
              "present illness. Gastrointestinal: negative for nausea, vomiting, "
              "diarrhea or melena. Genitourinary: negative for dysuria. "
              "Musculoskeletal: chronic bilateral knee pain at baseline. Neurologic: "
              "positive for lightheadedness. All other systems reviewed and negative."),
        ("h2", "PHYSICAL EXAMINATION"),
        ("kv2", [("Temperature", "38.9 C oral"),
                 ("Heart Rate", "112 bpm, irregularly irregular"),
                 ("Blood Pressure", "104/62 mmHg"),
                 ("Respiratory Rate", "26 breaths/min"),
                 ("SpO2", "88% on room air, 94% on 3 L nasal cannula"),
                 ("Weight / Height", "71.4 kg / 163 cm"),
                 ("Body Mass Index", "26.9 kg/m2"),
                 ("Pain Score", "6/10 right chest, pleuritic")]),
        ("p", "General: ill-appearing elderly female in mild respiratory distress, "
              "able to speak in short phrases. HEENT: mucous membranes dry, "
              "oropharynx without exudate. Neck: supple, no lymphadenopathy, jugular "
              "venous pressure not elevated. Chest: decreased breath sounds at the "
              "right base with coarse inspiratory crackles and egophony; no wheeze. "
              "Cardiac: irregularly irregular, tachycardic, no murmur, rub or gallop. "
              "Abdomen: soft, nontender, well-healed laparoscopic scars. Extremities: "
              "no edema, no calf tenderness. Skin: warm, no rash. Neurologic: alert "
              "and fully oriented, no focal deficit."),
        ("sig", "Harold T. Nakamura, MD  —  NPI 1487302956  —  04/06/2018 19:41"),
    ])

    # ---- 4. Medication reconciliation ----------------------------------
    P.append([
        ("h1", "MEDICATION RECONCILIATION AND INPATIENT ORDERS"),
        ("kv2", [("Reconciled By", "Oluwaseun Adeyemi, PharmD"),
                 ("Date", "04/06/2018 21:05"),
                 ("Verified With", "Patient and Daniel R. Whitfield"),
                 ("Pharmacy of Record", "Birchwood Drug, (319) 555-0148")]),
        ("rule",),
        ("h2", "INPATIENT MEDICATION ORDERS"),
        ("table", ["Medication", "Dose / Route", "Schedule", "Ordered By", "Start"],
         [["Ceftriaxone sodium", "1 g IV", "Q24H", "H. Nakamura, MD", "04/06"],
          ["Azithromycin", "500 mg IV", "Q24H", "H. Nakamura, MD", "04/06"],
          ["Methylprednisolone", "40 mg IV", "Q12H", "R. Achebe, MD", "04/07"],
          ["Ipratropium-albuterol", "3 mL NEB", "Q6H", "R. Achebe, MD", "04/07"],
          ["Apixaban", "5 mg PO", "BID", "S. Kaufmann, MD", "04/06"],
          ["Metoprolol tartrate", "12.5 mg PO", "Q6H", "S. Kaufmann, MD", "04/07"],
          ["Insulin lispro", "Sliding scale SC", "AC/HS", "I. Solberg, MD", "04/07"],
          ["Insulin glargine", "14 units SC", "Nightly", "I. Solberg, MD", "04/07"],
          ["Enoxaparin", "40 mg SC", "Daily", "H. Nakamura, MD", "04/06"],
          ["Acetaminophen", "650 mg PO", "Q6H PRN", "B. Ruiz-Alvarado, PA-C", "04/06"],
          ["Ondansetron", "4 mg IV", "Q8H PRN", "B. Ruiz-Alvarado, PA-C", "04/06"],
          ["Pantoprazole", "40 mg PO", "Daily", "H. Nakamura, MD", "04/06"]],
         [140, 100, 78, 130, 52]),
        ("h2", "MEDICATIONS HELD ON ADMISSION"),
        ("table", ["Medication", "Reason Held", "Resume Plan"],
         [["Metformin hydrochloride", "Acute illness, contrast exposure",
           "Resume 48 h post-contrast if creatinine stable"],
          ["Lisinopril", "Hypotension, SBP 104", "Resume when SBP > 110 sustained"],
          ["Metoprolol succinate ER", "Converted to short-acting", "Convert back at discharge"]],
         [150, 170, 190]),
        ("h2", "PHARMACY NOTES"),
        ("p", "Renal dosing reviewed; estimated creatinine clearance 58 mL/min by "
              "Cockcroft-Gault using an admission weight of 71.4 kg. Apixaban dose "
              "confirmed appropriate: the patient meets none of the reduction "
              "criteria. Azithromycin and metoprolol both prolong the QT interval; "
              "baseline QTc of 441 ms noted and telemetry monitoring requested. The "
              "patient's documented sulfonamide reaction was reviewed and no "
              "sulfonamide-containing agent has been ordered."),
        ("p", "Discharge prescriptions are to be routed to Birchwood Drug per the "
              "patient's preference. A ninety-day supply was requested by the "
              "patient's son on April 9, 2018; this requires confirmation with "
              "Meridian Blue PPO under policy MBP-448120977."),
        ("sig", "Oluwaseun Adeyemi, PharmD  —  04/06/2018 21:05"),
    ])

    # ---- 5. Labs 1 -----------------------------------------------------
    P.append([
        ("h1", "LABORATORY REPORT"),
        ("kv2", [("Patient", "Whitfield, Grace E."), ("MRN", "40-77-1592"),
                 ("Collected", "04/06/2018 15:10"), ("Received", "04/06/2018 15:28"),
                 ("Ordering Provider", "Harold T. Nakamura, MD"),
                 ("Performing Lab", "Saint Bartholomew Core Laboratory"),
                 ("Lab Director", "Tomasz Wieczorek, MD"), ("Accession", "L18-0406-44192")]),
        ("rule",),
        ("h2", "COMPLETE BLOOD COUNT WITH DIFFERENTIAL"),
        ("table", ["Analyte", "Result", "Flag", "Reference Range", "Units"],
         [["White blood cell count", "18.4", "H", "4.0 - 11.0", "K/uL"],
          ["Red blood cell count", "4.12", "", "3.90 - 5.20", "M/uL"],
          ["Hemoglobin", "11.8", "L", "12.0 - 16.0", "g/dL"],
          ["Hematocrit", "35.6", "L", "36.0 - 46.0", "%"],
          ["Mean corpuscular volume", "86.4", "", "80.0 - 100.0", "fL"],
          ["Platelet count", "398", "", "150 - 400", "K/uL"],
          ["Neutrophils", "84", "H", "40 - 70", "%"],
          ["Bands", "9", "H", "0 - 5", "%"],
          ["Lymphocytes", "5", "L", "20 - 45", "%"],
          ["Monocytes", "2", "", "2 - 10", "%"]],
         [170, 60, 40, 120, 60]),
        ("h2", "COMPREHENSIVE METABOLIC PANEL"),
        ("table", ["Analyte", "Result", "Flag", "Reference Range", "Units"],
         [["Sodium", "131", "L", "136 - 145", "mmol/L"],
          ["Potassium", "3.4", "L", "3.5 - 5.1", "mmol/L"],
          ["Chloride", "96", "L", "98 - 107", "mmol/L"],
          ["Carbon dioxide", "22", "", "22 - 29", "mmol/L"],
          ["Blood urea nitrogen", "28", "H", "7 - 20", "mg/dL"],
          ["Creatinine", "1.34", "H", "0.50 - 1.10", "mg/dL"],
          ["Glucose", "246", "H", "70 - 99", "mg/dL"],
          ["Calcium", "8.4", "L", "8.6 - 10.2", "mg/dL"],
          ["Albumin", "3.1", "L", "3.5 - 5.0", "g/dL"],
          ["Total bilirubin", "0.9", "", "0.2 - 1.2", "mg/dL"],
          ["Alkaline phosphatase", "118", "", "38 - 126", "U/L"],
          ["Aspartate aminotransferase", "41", "H", "10 - 35", "U/L"],
          ["Alanine aminotransferase", "36", "", "10 - 40", "U/L"]],
         [170, 60, 40, 120, 60]),
        ("small", "Critical values, if any, are telephoned to the ordering provider "
                  "and the read-back is documented. No critical value was reported "
                  "for this accession."),
    ])

    # ---- 6. Labs 2 + micro ---------------------------------------------
    P.append([
        ("h1", "LABORATORY REPORT (CONTINUED)"),
        ("h2", "ADDITIONAL CHEMISTRY AND SEROLOGY"),
        ("table", ["Analyte", "Result", "Flag", "Reference Range", "Units"],
         [["Lactic acid", "2.8", "H", "0.5 - 2.2", "mmol/L"],
          ["Procalcitonin", "3.44", "H", "< 0.50", "ng/mL"],
          ["C-reactive protein", "186", "H", "< 8", "mg/L"],
          ["Brain natriuretic peptide", "212", "H", "< 100", "pg/mL"],
          ["Troponin I, high sensitivity", "14", "", "< 18", "ng/L"],
          ["Hemoglobin A1c", "8.1", "H", "4.0 - 5.6", "%"],
          ["Thyroid stimulating hormone", "2.14", "", "0.45 - 4.50", "uIU/mL"],
          ["Magnesium", "1.6", "L", "1.7 - 2.4", "mg/dL"],
          ["Phosphorus", "2.9", "", "2.5 - 4.5", "mg/dL"]],
         [170, 60, 40, 120, 60]),
        ("h2", "ARTERIAL BLOOD GAS, ROOM AIR"),
        ("table", ["Analyte", "Result", "Reference Range", "Units"],
         [["pH", "7.47", "7.35 - 7.45", ""],
          ["pCO2", "31", "35 - 45", "mmHg"],
          ["pO2", "56", "80 - 100", "mmHg"],
          ["Bicarbonate", "22.4", "22 - 26", "mmol/L"],
          ["Oxygen saturation", "88", "95 - 100", "%"]],
         [170, 70, 130, 70]),
        ("h2", "MICROBIOLOGY"),
        ("kv2", [("Specimen", "Expectorated sputum"),
                 ("Collected", "04/06/2018 16:40"),
                 ("Accession", "M18-0406-1177"),
                 ("Gram Stain", "Many WBC, few epithelial cells, gram-positive "
                                "diplococci in pairs")]),
        ("p", "CULTURE, FINAL 04/09/2018: Heavy growth of Streptococcus pneumoniae. "
              "No other pathogen isolated. Blood cultures x2 drawn 04/06/2018 at "
              "15:05 and 15:20: no growth at five days, final. Urine pneumococcal "
              "antigen: POSITIVE. Legionella urinary antigen: NEGATIVE. Respiratory "
              "viral panel by PCR: NEGATIVE for influenza A, influenza B and "
              "respiratory syncytial virus. SARS testing not indicated at this "
              "encounter."),
        ("h2", "SUSCEPTIBILITIES - STREPTOCOCCUS PNEUMONIAE"),
        ("table", ["Antimicrobial", "MIC (ug/mL)", "Interpretation"],
         [["Penicillin", "0.03", "Susceptible"],
          ["Ceftriaxone", "0.12", "Susceptible"],
          ["Erythromycin", "> 4", "Resistant"],
          ["Levofloxacin", "1", "Susceptible"],
          ["Vancomycin", "0.5", "Susceptible"],
          ["Trimethoprim-sulfamethoxazole", "> 4", "Resistant"]],
         [200, 110, 150]),
        ("sig", "Reviewed by Tomasz Wieczorek, MD, Clinical Pathology  —  04/09/2018"),
    ])

    # ---- 7. Radiology CT -----------------------------------------------
    P.append([
        ("h1", "DIAGNOSTIC IMAGING REPORT"),
        ("kv2", [("Examination", "CT Angiography, Chest, With Contrast"),
                 ("Date of Service", "04/06/2018 17:52"),
                 ("Accession", "R18-114872"),
                 ("Referring Provider", "Harold T. Nakamura, MD"),
                 ("Interpreting Radiologist", "Marcus Delacroix, MD"),
                 ("Practice", "Blackhawk County Imaging Associates"),
                 ("NPI", "1629480371"),
                 ("Contrast", "Iohexol 350, 90 mL intravenous")]),
        ("rule",),
        ("h2", "CLINICAL INDICATION"),
        ("p", "Sixty-seven-year-old female with dyspnea, tachycardia, hypoxemia and "
              "leukocytosis. Rule out pulmonary embolism. Evaluate for pneumonia."),
        ("h2", "TECHNIQUE"),
        ("p", "Helical acquisition of the chest was performed from the lung apices "
              "through the adrenal glands following the intravenous administration of "
              "iodinated contrast material timed to the pulmonary arterial phase. "
              "Axial images were reconstructed at 1.25 mm and 3 mm; coronal and "
              "sagittal multiplanar reformations were generated. Dose-length product "
              "412 mGy-cm."),
        ("h2", "COMPARISON"),
        ("p", "Chest radiograph, two views, from earlier the same day. Prior chest CT "
              "from October 12, 2015 performed at Blackhawk County Imaging "
              "Associates."),
        ("h2", "FINDINGS"),
        ("p", "Pulmonary arteries: no filling defect is identified within the main, "
              "lobar, segmental or visualized subsegmental pulmonary arteries. "
              "Contrast opacification is adequate. No evidence of acute pulmonary "
              "embolism."),
        ("p", "Lungs and pleura: there is dense consolidation of the right lower lobe "
              "with air bronchograms, measuring approximately 9.4 x 7.1 cm in the "
              "axial plane. Patchy ground-glass opacity involves the posterior right "
              "middle lobe. A small right pleural effusion is present, layering "
              "dependently to a depth of 1.8 cm, without loculation or pleural "
              "enhancement to suggest empyema. Centrilobular and paraseptal emphysema "
              "is again noted in the upper lobes, unchanged from 2015. No pneumothorax."),
        ("p", "Mediastinum and hila: several subcentimeter right hilar and "
              "subcarinal lymph nodes are present, likely reactive. The heart is "
              "normal in size. No pericardial effusion. The thoracic aorta is of "
              "normal caliber with scattered atherosclerotic calcification."),
        ("p", "Upper abdomen: surgically absent gallbladder. Liver, spleen, adrenal "
              "glands and visualized kidneys are unremarkable. Osseous structures: no "
              "acute fracture. Mild thoracic spondylosis."),
        ("h2", "IMPRESSION"),
        ("bullets", [
            "No acute pulmonary embolism.",
            "Dense right lower lobe consolidation with adjacent right middle lobe "
            "ground-glass opacity, consistent with the clinical diagnosis of "
            "community-acquired pneumonia.",
            "Small simple-appearing right pleural effusion; no imaging feature of "
            "empyema. Recommend clinical correlation and follow-up radiography.",
            "Background emphysema, stable since 2015.",
        ]),
        ("sig", "Electronically signed by Marcus Delacroix, MD  —  04/06/2018 18:36"),
    ])

    # ---- 8. Radiology echo / US ----------------------------------------
    P.append([
        ("h1", "TRANSTHORACIC ECHOCARDIOGRAM"),
        ("kv2", [("Date of Service", "04/07/2018 10:15"),
                 ("Accession", "E18-00931"),
                 ("Sonographer", "Karen Fitzsimmons, RN, RDCS"),
                 ("Interpreting Cardiologist", "Steven Kaufmann, MD"),
                 ("Indication", "Atrial fibrillation with rapid ventricular response"),
                 ("Study Quality", "Adequate; limited subcostal windows")]),
        ("rule",),
        ("h2", "MEASUREMENTS"),
        ("table", ["Parameter", "Value", "Normal Range", "Units"],
         [["Left ventricular ejection fraction", "55 - 60", "> 55", "%"],
          ["LV internal diameter, diastole", "4.7", "3.9 - 5.3", "cm"],
          ["Interventricular septum", "1.2", "0.6 - 0.9", "cm"],
          ["Left atrial volume index", "41", "< 34", "mL/m2"],
          ["E/e' ratio, septal", "15", "< 8", ""],
          ["Tricuspid regurgitant velocity", "3.1", "< 2.8", "m/s"],
          ["Estimated PA systolic pressure", "44", "< 35", "mmHg"],
          ["Aortic valve area", "2.4", "> 2.0", "cm2"]],
         [220, 70, 100, 60]),
        ("h2", "FINDINGS"),
        ("p", "The left ventricle is normal in size with mildly increased wall "
              "thickness and preserved global systolic function. No regional wall "
              "motion abnormality is identified. Diastolic parameters are consistent "
              "with grade II diastolic dysfunction with elevated filling pressures. "
              "The left atrium is moderately dilated. The right ventricle is normal "
              "in size with preserved systolic function. There is mild tricuspid "
              "regurgitation permitting estimation of a mildly elevated pulmonary "
              "artery systolic pressure. The aortic valve is trileaflet with mild "
              "sclerosis and no stenosis. The mitral valve shows mild annular "
              "calcification with trace regurgitation. No pericardial effusion. No "
              "intracardiac thrombus is seen, although the left atrial appendage is "
              "not well visualized on transthoracic imaging."),
        ("h2", "IMPRESSION"),
        ("bullets", [
            "Preserved left ventricular ejection fraction, 55 to 60 percent.",
            "Mild concentric left ventricular hypertrophy with grade II diastolic "
            "dysfunction.",
            "Moderate left atrial enlargement, consistent with the history of "
            "paroxysmal atrial fibrillation.",
            "Mildly elevated estimated pulmonary artery systolic pressure at 44 mmHg.",
            "No transthoracic evidence of intracardiac thrombus; transesophageal "
            "imaging would be required for definitive appendage assessment.",
        ]),
        ("h2", "PORTABLE CHEST RADIOGRAPH, SINGLE VIEW"),
        ("kv2", [("Date of Service", "04/07/2018 06:05"),
                 ("Interpreting Radiologist", "Colette Beauchamp, MD")]),
        ("p", "Right lower lobe airspace opacity is unchanged in extent from the "
              "computed tomography of April 6. The small right effusion persists. "
              "Cardiomediastinal silhouette is stable. The right internal jugular "
              "central line terminates at the cavoatrial junction; no pneumothorax."),
        ("sig", "Steven Kaufmann, MD  —  Cardiology  —  04/07/2018 11:02"),
    ])

    # ---- 9-11. Progress notes ------------------------------------------
    progress = [
        ("HOSPITAL DAY 1 — PROGRESS NOTE", "April 7, 2018", "Rosalind Achebe, MD",
         "Pulmonary and Critical Care",
         "The patient reports that her breathing is modestly improved overnight but "
         "she remains dyspneic with minimal exertion and required an increase to 4 L "
         "by nasal cannula at 03:00. She had a temperature of 38.4 C at 04:00 which "
         "responded to acetaminophen. She slept poorly and describes the right-sided "
         "pleuritic pain as unchanged at 5 out of 10. Appetite is poor; she took "
         "approximately 20 percent of her breakfast tray.",
         "Afebrile at present. Heart rate 98 and irregular, blood pressure 108/64, "
         "respiratory rate 24, SpO2 93 percent on 4 L. Right basilar crackles with "
         "dullness to percussion and reduced tactile fremitus. No accessory muscle "
         "use at rest. Cardiac exam irregularly irregular without murmur. No "
         "peripheral edema. Point-of-care glucose values 246, 198 and 217 mg/dL over "
         "the past 24 hours.",
         ["Community-acquired pneumonia, right lower lobe, Streptococcus pneumoniae "
          "isolated from sputum with a positive urinary antigen. Continue ceftriaxone "
          "and azithromycin; narrow to a single agent once susceptibilities are "
          "final. Add scheduled ipratropium-albuterol nebulization and a short course "
          "of methylprednisolone given the COPD background.",
          "Hypoxemic respiratory failure, acute. Titrate oxygen to a saturation "
          "target of 90 to 94 percent. Incentive spirometry every hour while awake. "
          "Out of bed to chair with physical therapy consultation.",
          "Atrial fibrillation with rapid ventricular response, rate now improved on "
          "short-acting metoprolol. Continue apixaban; the CHA2DS2-VASc score is 4. "
          "Cardiology, Dr. Steven Kaufmann, following.",
          "Hyperglycemia in the setting of steroid administration. Endocrinology, Dr. "
          "Ingrid Solberg, has adjusted the basal insulin. Metformin remains held.",
          "Hyponatremia, mild, likely hypovolemic. Continue gentle isotonic fluid and "
          "recheck the basic metabolic panel in the morning."],
         "Rosalind Achebe, MD  —  04/07/2018 08:22"),
        ("HOSPITAL DAY 2 — PROGRESS NOTE", "April 8, 2018", "Peter Vandermolen, DO",
         "Internal Medicine (Cross-cover)",
         "Overnight the patient was noted to have an episode of confusion at "
         "approximately 02:30, calling for her late husband and attempting to climb "
         "out of bed. Ms. Lucille Marchetti, RN, applied a bed alarm and the "
         "cross-covering physician was notified. The episode resolved by 05:00 "
         "without pharmacologic intervention. This morning she is fully oriented and "
         "has no recollection of the event. Her son, Daniel R. Whitfield, was "
         "telephoned at (319) 555-0192 and updated at 07:15.",
         "Temperature 37.4 C, heart rate 88, blood pressure 116/70, respiratory rate "
         "20, SpO2 94 percent on 2 L. Crackles persist at the right base but the "
         "aeration is improved. Mini-mental status screening is at baseline. No focal "
         "neurologic deficit.",
         ["Hyperactive delirium, resolved. Likely multifactorial from infection, "
          "hypoxemia, corticosteroid exposure and sleep disruption. Non-pharmacologic "
          "protocol initiated: sleep hygiene, daytime mobilization, hearing aid and "
          "spectacles at the bedside, orientation cues. Avoid anticholinergics and "
          "benzodiazepines. Deliriogenic medication review completed with Oluwaseun "
          "Adeyemi, PharmD.",
          "Pneumonia, improving. Oxygen requirement down from 4 L to 2 L. Repeat "
          "inflammatory markers ordered for the morning.",
          "Hypokalemia and hypomagnesemia repleted overnight with 40 mEq of potassium "
          "chloride orally and 2 g of magnesium sulfate intravenously.",
          "Deep venous thrombosis prophylaxis is provided by therapeutic apixaban; "
          "enoxaparin has been discontinued to avoid duplication.",
          "Goals of care: the patient reiterates that she wishes full treatment at "
          "this time. Her durable power of attorney for health care names her son."],
         "Peter Vandermolen, DO  —  04/08/2018 08:40"),
        ("HOSPITAL DAY 3 — PROGRESS NOTE", "April 9, 2018", "Harold T. Nakamura, MD",
         "Internal Medicine",
         "The patient states this is the best she has felt since admission. She "
         "walked the length of the hallway twice with physical therapy yesterday "
         "afternoon and maintained saturations above 92 percent on room air during "
         "ambulation. Cough is now loose and less frequent. She ate most of her "
         "dinner and all of her breakfast. She asks when she may go home and whether "
         "she will need oxygen at the apartment.",
         "Afebrile for 36 hours. Heart rate 76 and now regular on telemetry review, "
         "blood pressure 124/74, respiratory rate 18, SpO2 94 percent on room air at "
         "rest and 92 percent with ambulation. Right basilar crackles are "
         "substantially reduced. No edema.",
         ["Community-acquired pneumonia, responding. Sputum culture final with "
          "penicillin-susceptible Streptococcus pneumoniae; azithromycin "
          "discontinued and therapy narrowed. Plan to transition to oral amoxicillin "
          "to complete a total seven-day course.",
          "Corticosteroid taper: methylprednisolone reduced and to be converted to "
          "oral prednisone 20 mg daily for three additional days.",
          "Atrial fibrillation, now in sinus rhythm since 04/08 at 22:00. Resume "
          "metoprolol succinate 50 mg daily at discharge. Continue apixaban "
          "indefinitely.",
          "Diabetes mellitus: glycemic control improving as steroids taper. "
          "Metformin may resume tomorrow given a creatinine of 1.02 mg/dL, now 72 "
          "hours from contrast exposure.",
          "Disposition: anticipate discharge home on 04/13/2018 pending an ambulatory "
          "oxygen saturation study and the completion of care-management "
          "arrangements. Home health referral placed to Willow Creek Skilled Nursing "
          "Facility outpatient services."],
         "Harold T. Nakamura, MD  —  04/09/2018 09:05"),
    ]
    for title, date, author, service, subj, obj, plan, sig in progress:
        P.append([
            ("h1", title),
            ("kv2", [("Date of Service", date), ("Author", author),
                     ("Service", service), ("Location", "5 North, Room 512-A")]),
            ("rule",),
            ("h2", "SUBJECTIVE"),
            ("p", subj),
            ("h2", "OBJECTIVE"),
            ("p", obj),
            ("h2", "ASSESSMENT AND PLAN"),
            ("numbered", plan),
            ("sig", sig),
        ])

    # ---- 12. Nursing flowsheet -----------------------------------------
    P.append([
        ("h1", "NURSING FLOWSHEET — VITAL SIGNS AND INTAKE/OUTPUT"),
        ("kv2", [("Unit", "5 North"), ("Room / Bed", "512-A"),
                 ("Charge Nurse", "Karen Fitzsimmons, RN"),
                 ("Primary Nurse, Days", "Lucille Marchetti, RN")]),
        ("rule",),
        ("h2", "VITAL SIGNS"),
        ("table", ["Date/Time", "Temp C", "HR", "BP", "RR", "SpO2 / O2", "Pain"],
         [["04/06 14:30", "38.9", "112", "104/62", "26", "88% RA", "6"],
          ["04/06 20:00", "38.6", "108", "108/66", "24", "94% 3L", "5"],
          ["04/07 00:00", "38.1", "104", "110/68", "22", "93% 3L", "4"],
          ["04/07 04:00", "38.4", "110", "102/60", "24", "91% 4L", "5"],
          ["04/07 08:00", "37.6", "98", "108/64", "24", "93% 4L", "5"],
          ["04/07 16:00", "37.2", "92", "114/70", "20", "94% 3L", "3"],
          ["04/08 00:00", "37.5", "96", "112/68", "20", "94% 2L", "3"],
          ["04/08 08:00", "37.4", "88", "116/70", "20", "94% 2L", "2"],
          ["04/08 16:00", "36.9", "84", "118/72", "18", "95% 2L", "2"],
          ["04/09 08:00", "36.8", "76", "124/74", "18", "94% RA", "1"],
          ["04/09 20:00", "36.7", "78", "122/76", "18", "95% RA", "1"],
          ["04/10 08:00", "36.6", "74", "126/78", "17", "95% RA", "1"]],
         [78, 50, 38, 62, 36, 74, 40]),
        ("h2", "INTAKE AND OUTPUT, 24-HOUR TOTALS"),
        ("table", ["Date", "PO (mL)", "IV (mL)", "Total In", "Urine (mL)", "Total Out", "Net"],
         [["04/06", "400", "1200", "1600", "950", "950", "+650"],
          ["04/07", "760", "1000", "1760", "1420", "1420", "+340"],
          ["04/08", "1100", "500", "1600", "1680", "1680", "-80"],
          ["04/09", "1350", "0", "1350", "1510", "1510", "-160"]],
         [60, 62, 62, 62, 74, 66, 54]),
        ("h2", "POINT-OF-CARE GLUCOSE"),
        ("table", ["Date/Time", "Glucose (mg/dL)", "Insulin Given", "Nurse"],
         [["04/07 07:30", "246", "6 units lispro", "L. Marchetti, RN"],
          ["04/07 11:45", "198", "4 units lispro", "L. Marchetti, RN"],
          ["04/07 17:00", "217", "5 units lispro", "E. Hargrove, RN"],
          ["04/07 21:30", "184", "14 units glargine", "E. Hargrove, RN"],
          ["04/08 07:30", "163", "3 units lispro", "L. Marchetti, RN"],
          ["04/09 07:30", "138", "0 units", "L. Marchetti, RN"]],
         [90, 110, 120, 130]),
        ("small", "Falls risk: Morse score 55, high. Braden score 18, mild risk. "
                  "Bed alarm active 04/08 02:30 through 04/09 08:00."),
    ])

    # ---- 13. Cardiology consult ----------------------------------------
    P.append([
        ("h1", "CONSULTATION REPORT — CARDIOLOGY"),
        ("kv2", [("Date of Service", "April 7, 2018"),
                 ("Consultant", "Steven Kaufmann, MD"),
                 ("Requested By", "Harold T. Nakamura, MD"),
                 ("Reason for Consultation", "Atrial fibrillation with rapid "
                                             "ventricular response")]),
        ("rule",),
        ("h2", "REASON FOR CONSULTATION"),
        ("p", "Thank you for the kind referral of Ms. Grace Eleanor Whitfield, a "
              "67-year-old woman admitted with community-acquired pneumonia, for "
              "evaluation of atrial fibrillation with a rapid ventricular response."),
        ("h2", "CARDIAC HISTORY"),
        ("p", "Paroxysmal atrial fibrillation was first documented in June 2014 "
              "during an episode of palpitations evaluated at Cedar Falls Family "
              "Practice. She was started on apixaban at that time and has remained "
              "adherent. A prior transthoracic echocardiogram in 2015 demonstrated "
              "normal systolic function. She has never undergone cardioversion or "
              "ablation. There is no history of coronary artery disease, and a "
              "stress test in 2013 was normal."),
        ("h2", "ELECTROCARDIOGRAM"),
        ("p", "The tracing from 04/06/2018 at 14:35 demonstrates atrial fibrillation "
              "at a ventricular rate of 118 beats per minute with a narrow QRS "
              "complex, nonspecific ST-T changes in the lateral leads and a corrected "
              "QT interval of 441 ms. A repeat tracing on 04/09/2018 at 06:20 shows "
              "normal sinus rhythm at 74 beats per minute with resolution of the ST-T "
              "changes."),
        ("h2", "ASSESSMENT"),
        ("p", "The arrhythmia is most consistent with a paroxysm of atrial "
              "fibrillation provoked by acute infection, hypoxemia, electrolyte "
              "derangement and adrenergic stress rather than by primary progression "
              "of atrial disease. The patient converted spontaneously to sinus rhythm "
              "on hospital day 2 following correction of hypokalemia and "
              "hypomagnesemia and treatment of the underlying pneumonia."),
        ("h2", "RECOMMENDATIONS"),
        ("numbered", [
            "Continue apixaban 5 mg twice daily indefinitely. The CHA2DS2-VASc score "
            "is 4 and the HAS-BLED score is 2; the net clinical benefit favors "
            "continued anticoagulation.",
            "Resume metoprolol succinate 50 mg daily at discharge in place of the "
            "short-acting formulation.",
            "Maintain serum potassium above 4.0 mmol/L and magnesium above 2.0 mg/dL "
            "for the remainder of the admission.",
            "No antiarrhythmic agent is indicated at present. Should recurrent "
            "symptomatic episodes occur after recovery, outpatient consideration of "
            "flecainide or ablation would be reasonable.",
            "Outpatient follow-up in the cardiology clinic in four weeks. An "
            "appointment has been arranged for May 11, 2018 at 10:30 with this "
            "consultant.",
            "A fourteen-day ambulatory rhythm monitor will be dispensed at discharge; "
            "the patient should return it to the address printed on the device kit.",
        ]),
        ("p", "I appreciate the opportunity to participate in the care of Ms. "
              "Whitfield. Please contact me at (319) 555-0148, extension 4471, with "
              "any question. Cardiology will follow while she remains an inpatient."),
        ("sig", "Steven Kaufmann, MD, FACC  —  Cardiology  —  04/07/2018 13:20"),
    ])

    # ---- 14. Nephrology / endocrine consult -----------------------------
    P.append([
        ("h1", "CONSULTATION REPORT — ENDOCRINOLOGY AND NEPHROLOGY"),
        ("kv2", [("Date of Service", "April 8, 2018"),
                 ("Endocrinology Consultant", "Ingrid Solberg, MD"),
                 ("Nephrology Consultant", "Devendra Ramaswamy, MD"),
                 ("Requested By", "Rosalind Achebe, MD")]),
        ("rule",),
        ("h2", "ENDOCRINOLOGY — STEROID-ASSOCIATED HYPERGLYCEMIA"),
        ("p", "Ms. Whitfield has type 2 diabetes mellitus of fifteen years' duration, "
              "previously managed with metformin monotherapy and an outpatient "
              "hemoglobin A1c of 7.8 percent in January 2018. The inpatient value of "
              "8.1 percent suggests modest deterioration predating this admission. "
              "Glucose values rose to a peak of 246 mg/dL after the initiation of "
              "methylprednisolone."),
        ("p", "A basal-bolus regimen has been substituted for sliding-scale coverage "
              "alone. Insulin glargine 14 units nightly with insulin lispro before "
              "meals has produced values in the 130 to 180 mg/dL range by hospital "
              "day 3. As the corticosteroid is tapered the basal dose should be "
              "reduced by approximately 20 percent per step to avoid hypoglycemia."),
        ("bullets", [
            "Resume metformin 1000 mg twice daily once 72 hours have elapsed from "
            "iodinated contrast and the creatinine has returned to baseline.",
            "Discontinue insulin at discharge if glucose values remain below 180 "
            "mg/dL off corticosteroid.",
            "Arrange outpatient diabetes education; a referral has been sent to the "
            "certified diabetes educator at Cedar Falls Family Practice.",
            "Repeat hemoglobin A1c in three months, approximately July 2018.",
        ]),
        ("h2", "NEPHROLOGY — ACUTE KIDNEY INJURY, RESOLVED"),
        ("p", "The admission creatinine of 1.34 mg/dL represents a rise from a "
              "baseline of 0.94 mg/dL recorded in January 2018, meeting criteria for "
              "stage 1 acute kidney injury. The pattern of a bland urinary sediment, "
              "a fractional excretion of sodium below one percent and prompt response "
              "to volume resuscitation is consistent with a prerenal insult from "
              "sepsis and poor oral intake. Contrast nephropathy is an additional "
              "consideration given the computed tomography of April 6, although the "
              "temporal course favors the prerenal mechanism."),
        ("table", ["Date", "Creatinine (mg/dL)", "BUN (mg/dL)", "eGFR (mL/min/1.73m2)"],
         [["01/22/2018", "0.94", "16", "62"],
          ["04/06/2018", "1.34", "28", "41"],
          ["04/07/2018", "1.21", "24", "46"],
          ["04/08/2018", "1.08", "19", "53"],
          ["04/09/2018", "1.02", "17", "57"]],
         [90, 130, 110, 160]),
        ("bullets", [
            "Avoid nonsteroidal anti-inflammatory drugs indefinitely.",
            "Hold lisinopril until the outpatient visit; Dr. Yvette Okonkwo may "
            "resume it once the creatinine is confirmed stable.",
            "Recheck a basic metabolic panel within seven days of discharge.",
            "No indication for renal ultrasound or nephrology follow-up at this time.",
        ]),
        ("sig", "Ingrid Solberg, MD  —  Endocrinology  —  04/08/2018 14:10"),
        ("sig", "Devendra Ramaswamy, MD  —  Nephrology  —  04/08/2018 16:45"),
    ])

    # ---- 15. Operative report -------------------------------------------
    P.append([
        ("h1", "OPERATIVE REPORT"),
        ("kv2", [("Date of Procedure", "April 10, 2018"),
                 ("Surgeon", "Ahmad Farhadi, MD"),
                 ("Assistant", "Bethany Ruiz-Alvarado, PA-C"),
                 ("Anesthesiologist", "Colette Beauchamp, MD"),
                 ("Preoperative Diagnosis", "Persistent right pleural effusion"),
                 ("Postoperative Diagnosis", "Same; loculated parapneumonic effusion"),
                 ("Procedure", "Ultrasound-guided thoracentesis, right, with "
                               "pigtail catheter placement"),
                 ("Anesthesia", "Local, 1% lidocaine; moderate sedation"),
                 ("Estimated Blood Loss", "Less than 5 mL"),
                 ("Specimens", "Pleural fluid, 750 mL, to cytology and microbiology"),
                 ("Complications", "None")]),
        ("rule",),
        ("h2", "INDICATION"),
        ("p", "Ms. Grace E. Whitfield is a 67-year-old woman on hospital day 4 for "
              "pneumococcal pneumonia whose right pleural effusion enlarged on "
              "follow-up radiography despite appropriate antimicrobial therapy. "
              "Diagnostic and therapeutic drainage was recommended. Risks including "
              "bleeding, infection, pneumothorax, re-expansion pulmonary edema and "
              "the possible need for a larger tube or surgical decortication were "
              "discussed with the patient and with her son by telephone. Written "
              "informed consent was obtained and placed in the record."),
        ("h2", "DESCRIPTION OF PROCEDURE"),
        ("p", "The patient was positioned upright at the edge of the bed with her "
              "arms supported on a bedside table. A time-out was performed with the "
              "bedside nurse, Ms. Karen Fitzsimmons, RN, confirming patient identity "
              "by two identifiers, the procedure, the laterality and the availability "
              "of consent. Ultrasound survey of the right hemithorax demonstrated a "
              "moderate effusion with internal septations at the eighth intercostal "
              "space in the posterior axillary line."),
        ("p", "The skin was prepared with chlorhexidine and draped in a sterile "
              "fashion. The skin, subcutaneous tissue and parietal pleura were "
              "infiltrated with 8 mL of one percent lidocaine. Under direct "
              "ultrasound guidance an 18-gauge introducer needle was advanced over "
              "the superior margin of the ninth rib until pleural fluid was freely "
              "aspirated. A guidewire was passed without resistance, the tract was "
              "dilated, and a 12 French pigtail catheter was advanced over the wire "
              "and secured at the skin with a drain-fix device and a 2-0 nylon "
              "suture."),
        ("p", "Seven hundred fifty milliliters of turbid amber fluid were drained "
              "slowly with intermittent clamping to limit the risk of re-expansion "
              "edema. The patient tolerated the procedure well without cough or chest "
              "discomfort. The catheter was connected to a water-seal drainage system "
              "at minus 20 centimeters of water. A post-procedure chest radiograph "
              "confirmed appropriate catheter position, a substantial reduction in "
              "the effusion and no pneumothorax."),
        ("h2", "DISPOSITION"),
        ("p", "The patient returned to Room 512-A in stable condition. Pleural fluid "
              "studies were sent for cell count, chemistry, Gram stain, culture and "
              "cytology. Vital signs are to be recorded every fifteen minutes for one "
              "hour and the drainage output charted every shift."),
        ("sig", "Ahmad Farhadi, MD  —  Interventional Pulmonology  —  "
                "04/10/2018 15:12"),
    ])

    # ---- 16. Anesthesia / sedation record --------------------------------
    P.append([
        ("h1", "MODERATE SEDATION RECORD"),
        ("kv2", [("Date", "04/10/2018"), ("Location", "Bedside, 5 North 512-A"),
                 ("Sedation Provider", "Colette Beauchamp, MD"),
                 ("Monitoring Nurse", "Karen Fitzsimmons, RN"),
                 ("ASA Classification", "III"),
                 ("Mallampati", "II"), ("NPO Since", "04/10/2018 06:00")]),
        ("rule",),
        ("h2", "PRE-PROCEDURE ASSESSMENT"),
        ("p", "Airway examination unremarkable with adequate mouth opening and "
              "thyromental distance. Dentition intact. No history of adverse reaction "
              "to sedation or anesthesia. Cardiopulmonary status optimized. Consent "
              "verified. Reversal agents naloxone and flumazenil confirmed available "
              "at the bedside."),
        ("h2", "MEDICATIONS ADMINISTERED"),
        ("table", ["Time", "Agent", "Dose", "Route", "Given By"],
         [["14:32", "Midazolam", "1 mg", "IV", "C. Beauchamp, MD"],
          ["14:34", "Fentanyl citrate", "50 mcg", "IV", "C. Beauchamp, MD"],
          ["14:46", "Midazolam", "1 mg", "IV", "C. Beauchamp, MD"],
          ["14:47", "Lidocaine 1%", "8 mL", "SC/Local", "A. Farhadi, MD"]],
         [55, 140, 70, 70, 145]),
        ("h2", "INTRA-PROCEDURE MONITORING"),
        ("table", ["Time", "HR", "BP", "RR", "SpO2", "Sedation Score"],
         [["14:30", "78", "126/76", "18", "95%", "0 - alert"],
          ["14:35", "74", "120/72", "16", "96%", "1 - drowsy"],
          ["14:40", "72", "118/70", "14", "97%", "2 - eyes closed"],
          ["14:45", "70", "114/68", "13", "96%", "2 - eyes closed"],
          ["14:50", "72", "116/70", "14", "97%", "2 - eyes closed"],
          ["15:00", "76", "122/74", "16", "96%", "1 - drowsy"],
          ["15:10", "78", "124/76", "18", "95%", "0 - alert"]],
         [60, 50, 80, 50, 60, 130]),
        ("h2", "RECOVERY"),
        ("p", "The patient met discharge-from-sedation criteria at 15:40 with an "
              "Aldrete score of 10. She was alert and fully oriented, maintained her "
              "airway without support, had stable vital signs within ten percent of "
              "baseline and reported no nausea. Oxygen was weaned to room air with a "
              "saturation of 95 percent. Post-sedation instructions were reviewed "
              "with the patient and with Ms. Lucille Marchetti, RN."),
        ("kv2", [("Total Sedation Time", "38 minutes"),
                 ("Complications", "None"),
                 ("Reversal Agents Used", "None"),
                 ("Aldrete Score at Discharge", "10 of 10")]),
        ("sig", "Colette Beauchamp, MD  —  04/10/2018 15:44"),
    ])

    # ---- 17. Pathology ---------------------------------------------------
    P.append([
        ("h1", "SURGICAL PATHOLOGY AND CYTOLOGY REPORT"),
        ("kv2", [("Accession", "S18-6640"), ("Collected", "04/10/2018 14:55"),
                 ("Received", "04/10/2018 16:20"), ("Reported", "04/11/2018 11:30"),
                 ("Pathologist", "Tomasz Wieczorek, MD"),
                 ("Submitting Physician", "Ahmad Farhadi, MD")]),
        ("rule",),
        ("h2", "SPECIMEN"),
        ("p", "A. Pleural fluid, right, 750 mL, submitted fresh in a sterile "
              "container, labeled with the patient's name and medical record number."),
        ("h2", "PLEURAL FLUID ANALYSIS"),
        ("table", ["Analyte", "Result", "Reference / Criterion", "Units"],
         [["Appearance", "Turbid, amber", "Clear, straw", ""],
          ["Nucleated cell count", "8,400", "< 1,000", "cells/uL"],
          ["Neutrophils", "78", "< 50", "%"],
          ["Lymphocytes", "16", "", "%"],
          ["Protein, fluid", "4.2", "", "g/dL"],
          ["Protein, fluid/serum ratio", "0.68", "> 0.5 exudative", ""],
          ["LDH, fluid", "412", "", "U/L"],
          ["LDH, fluid/serum ratio", "0.71", "> 0.6 exudative", ""],
          ["Glucose, fluid", "48", "< 60 complicated", "mg/dL"],
          ["pH, fluid", "7.18", "< 7.20 complicated", ""],
          ["Adenosine deaminase", "18", "< 40", "U/L"]],
         [180, 70, 150, 60]),
        ("h2", "MICROSCOPIC DESCRIPTION"),
        ("p", "Cytospin preparations show abundant neutrophils with degenerative "
              "changes admixed with reactive mesothelial cells and scattered "
              "lymphocytes and histiocytes. No fungal or acid-fast organisms are "
              "identified on special stains. There is no evidence of malignancy. "
              "Occasional gram-positive cocci in pairs are identified on the "
              "concurrent Gram stain."),
        ("h2", "DIAGNOSIS"),
        ("bullets", [
            "A. PLEURAL FLUID, RIGHT: Acute inflammatory exudate with reactive "
            "mesothelial cells.",
            "NEGATIVE FOR MALIGNANT CELLS.",
            "Biochemical profile meets Light's criteria for an exudate and the "
            "thresholds for a complicated parapneumonic effusion.",
        ]),
        ("h2", "COMMENT"),
        ("p", "The combination of a fluid pH below 7.20, a fluid glucose below 60 "
              "mg/dL and a positive Gram stain supports the classification of a "
              "complicated parapneumonic effusion for which continued catheter "
              "drainage is appropriate. Correlation with the culture result, reported "
              "separately under accession M18-0410-2043, is recommended. This case "
              "was reviewed in intradepartmental consultation with Dr. Colette "
              "Beauchamp on April 11, 2018."),
        ("sig", "Tomasz Wieczorek, MD  —  Anatomic and Clinical Pathology  —  "
                "04/11/2018 11:30"),
    ])

    # ---- 18. Therapy and care management ---------------------------------
    P.append([
        ("h1", "PHYSICAL THERAPY EVALUATION AND CARE MANAGEMENT NOTE"),
        ("kv2", [("Date of Service", "April 11, 2018"),
                 ("Physical Therapist", "Bethany Ruiz-Alvarado, PA-C, on behalf of "
                                        "Rehabilitation Services"),
                 ("Case Manager", "Karen Fitzsimmons, RN, CCM"),
                 ("Referring Provider", "Harold T. Nakamura, MD")]),
        ("rule",),
        ("h2", "PHYSICAL THERAPY EVALUATION"),
        ("p", "Prior level of function: independent in all basic and instrumental "
              "activities of daily living. The patient drove, managed her own "
              "medications and finances, shopped independently and climbed one flight "
              "of stairs to reach her apartment without assistive device."),
        ("table", ["Measure", "Result", "Interpretation"],
         [["6-minute walk distance", "218 m", "Reduced for age and sex"],
          ["Lowest SpO2 on ambulation", "91% on room air", "No supplemental O2 needed"],
          ["Borg dyspnea score", "4 of 10", "Moderate"],
          ["Five times sit-to-stand", "16.2 s", "Elevated fall risk"],
          ["Gait speed", "0.71 m/s", "Below community ambulation threshold"],
          ["Berg Balance Scale", "44 of 56", "Moderate fall risk"]],
         [180, 130, 180]),
        ("p", "Assessment: deconditioning superimposed on chronic obstructive "
              "pulmonary disease and bilateral knee osteoarthritis, with a moderate "
              "fall risk. The patient is safe to return home provided that stair "
              "training is completed and a rolling walker is dispensed for community "
              "distances."),
        ("bullets", [
            "Home exercise program issued in large print and reviewed with the patient.",
            "Rolling walker with seat dispensed 04/12/2018; the patient demonstrated "
            "safe use on level ground and on stairs with a rail.",
            "Home health physical therapy, two visits per week for three weeks, "
            "arranged through Willow Creek Skilled Nursing Facility outpatient "
            "services.",
            "Referral to outpatient pulmonary rehabilitation; the patient is to "
            "telephone (563) 555-0771 to schedule an intake appointment.",
        ]),
        ("h2", "CARE MANAGEMENT AND DISCHARGE PLANNING"),
        ("p", "Ms. Whitfield lives alone at 1427 Birchwood Terrace, Apartment 3B, "
              "Cedar Falls, Iowa. Her son, Daniel R. Whitfield, has arranged to stay "
              "with her for the first five days after discharge and will transport "
              "her to follow-up appointments. Her sister, Priscilla Vance, will "
              "assist thereafter."),
        ("table", ["Service", "Vendor / Agency", "Status", "Contact"],
         [["Home health PT", "Willow Creek SNF Outpatient", "Authorized", "(319) 555-0148"],
          ["Durable medical equipment", "Blackhawk Home Medical", "Delivered 04/12", "(319) 555-0192"],
          ["Pulmonary rehabilitation", "Saint Bartholomew Rehab", "Pending intake", "(563) 555-0771"],
          ["Meal delivery, 14 days", "Cedar Valley Meals", "Confirmed", "(319) 555-0148"]],
         [140, 160, 110, 100]),
        ("p", "Insurance authorization for home health services was obtained from "
              "Meridian Blue PPO on April 11, 2018 under prior authorization number "
              "PA-2018-77412. No patient financial responsibility is anticipated "
              "beyond the standard copayment."),
        ("sig", "Karen Fitzsimmons, RN, CCM  —  04/11/2018 16:05"),
    ])

    # ---- 19. Discharge summary 1 -----------------------------------------
    P.append([
        ("h1", "DISCHARGE SUMMARY"),
        ("kv2", [("Patient", "Whitfield, Grace Eleanor"), ("MRN", "40-77-1592"),
                 ("Date of Birth", "03/14/1951"),
                 ("Date of Admission", "April 6, 2018"),
                 ("Date of Discharge", "April 13, 2018"),
                 ("Length of Stay", "7 days"),
                 ("Attending Physician", "Harold T. Nakamura, MD"),
                 ("Discharge Disposition", "Home with home health services")]),
        ("rule",),
        ("h2", "DISCHARGE DIAGNOSES"),
        ("numbered", [
            "Community-acquired pneumonia, right lower lobe, due to Streptococcus "
            "pneumoniae, with complicated parapneumonic effusion (principal).",
            "Acute hypoxemic respiratory failure, resolved.",
            "Paroxysmal atrial fibrillation with rapid ventricular response, "
            "converted to sinus rhythm.",
            "Acute kidney injury, stage 1, prerenal, resolved.",
            "Steroid-associated hyperglycemia in type 2 diabetes mellitus.",
            "Hyperactive delirium, resolved.",
            "Chronic obstructive pulmonary disease, GOLD stage II.",
            "Essential hypertension.",
            "Hyponatremia, hypokalemia and hypomagnesemia, corrected.",
        ]),
        ("h2", "PROCEDURES PERFORMED"),
        ("bullets", [
            "Computed tomographic angiography of the chest, 04/06/2018.",
            "Transthoracic echocardiogram, 04/07/2018.",
            "Ultrasound-guided thoracentesis with pigtail catheter placement, right, "
            "04/10/2018, by Ahmad Farhadi, MD.",
            "Catheter removal, 04/12/2018, without complication.",
        ]),
        ("h2", "HOSPITAL COURSE"),
        ("p", "Ms. Whitfield presented to the emergency department on April 6, 2018 "
              "with five days of dyspnea and productive cough and was found to be "
              "febrile, tachycardic and hypoxemic with a saturation of 88 percent on "
              "room air. Chest computed tomography excluded pulmonary embolism and "
              "demonstrated dense right lower lobe consolidation with a small "
              "effusion. She was admitted to the medical floor and begun on "
              "ceftriaxone and azithromycin."),
        ("p", "Sputum culture grew penicillin-susceptible Streptococcus pneumoniae "
              "with a positive urinary antigen, and therapy was narrowed on hospital "
              "day 3. She required up to 4 L of supplemental oxygen on hospital day 1 "
              "and was weaned to room air by hospital day 3. A course of "
              "methylprednisolone was given for the obstructive component and tapered "
              "to oral prednisone."),
        ("p", "Her presenting atrial fibrillation with a ventricular rate of 118 was "
              "managed with rate control and electrolyte repletion; she converted "
              "spontaneously to sinus rhythm on the evening of April 8. Cardiology, "
              "Dr. Steven Kaufmann, recommended continuation of apixaban and a return "
              "to long-acting metoprolol at discharge. An episode of hyperactive "
              "delirium on the night of April 7 to 8 resolved with non-pharmacologic "
              "measures alone."),
        ("p", "A persistent right effusion enlarged on follow-up imaging and was "
              "drained on April 10 by Dr. Ahmad Farhadi, yielding 750 mL of an "
              "exudate meeting criteria for a complicated parapneumonic effusion. The "
              "catheter drained a further 340 mL over 48 hours and was removed on "
              "April 12 after output fell below 50 mL per day. Post-removal "
              "radiography showed no reaccumulation and no pneumothorax."),
    ])

    # ---- 20. Discharge summary 2 -----------------------------------------
    P.append([
        ("h1", "DISCHARGE SUMMARY (CONTINUED)"),
        ("h2", "CONDITION AT DISCHARGE"),
        ("p", "The patient is afebrile, ambulating with a rolling walker, saturating "
              "94 percent on room air at rest and 92 percent with ambulation, "
              "tolerating a regular carbohydrate-modified diet and fully oriented. "
              "Her white blood cell count has fallen to 8.9 K/uL and her creatinine "
              "is 0.98 mg/dL."),
        ("h2", "DISCHARGE MEDICATIONS"),
        ("table", ["Medication", "Dose", "Route", "Frequency", "Duration"],
         [["Amoxicillin", "875 mg", "PO", "BID", "Through 04/16/2018"],
          ["Prednisone", "20 mg", "PO", "Daily", "Through 04/15/2018"],
          ["Apixaban", "5 mg", "PO", "BID", "Continuous"],
          ["Metoprolol succinate ER", "50 mg", "PO", "Daily", "Continuous"],
          ["Metformin hydrochloride", "1000 mg", "PO", "BID", "Continuous"],
          ["Atorvastatin calcium", "40 mg", "PO", "Nightly", "Continuous"],
          ["Tiotropium bromide", "18 mcg", "INH", "Daily", "Continuous"],
          ["Albuterol HFA", "90 mcg", "INH", "Q4H PRN", "Continuous"],
          ["Pantoprazole", "40 mg", "PO", "Daily", "Through 04/20/2018"],
          ["Acetaminophen", "650 mg", "PO", "Q6H PRN", "As needed"]],
         [150, 80, 60, 90, 130]),
        ("p", "STOPPED AT DISCHARGE: lisinopril, held pending outpatient reassessment "
              "of renal function; azithromycin and ceftriaxone, course complete; all "
              "inpatient insulin."),
        ("h2", "FOLLOW-UP APPOINTMENTS"),
        ("table", ["Provider", "Specialty", "Date / Time", "Location"],
         [["Yvette Okonkwo, MD", "Primary Care", "04/18/2018 09:00", "Cedar Falls Family Practice"],
          ["Steven Kaufmann, MD", "Cardiology", "05/11/2018 10:30", "Saint Bartholomew Cardiology"],
          ["Rosalind Achebe, MD", "Pulmonary", "05/04/2018 14:15", "Saint Bartholomew Pulmonary"],
          ["Ingrid Solberg, MD", "Endocrinology", "07/09/2018 11:00", "Saint Bartholomew Endocrine"]],
         [140, 100, 110, 160]),
        ("h2", "PENDING RESULTS AT DISCHARGE"),
        ("p", "Pleural fluid culture, accession M18-0410-2043: no growth at 48 hours; "
              "the final result will be routed to Dr. Harold T. Nakamura and Dr. "
              "Yvette Okonkwo. The fourteen-day rhythm monitor was applied 04/13/2018."),
        ("h2", "PATIENT INSTRUCTIONS"),
        ("numbered", [
            "Complete the full course of amoxicillin even if you feel entirely well.",
            "Return to the emergency department for fever above 38.3 C, worsening "
            "shortness of breath, chest pain, coughing up blood, or confusion.",
            "Check your blood sugar twice daily and record the values; bring the log "
            "to your appointment on April 18.",
            "Use the incentive spirometer ten times each hour while awake for two "
            "weeks.",
            "Do not take ibuprofen, naproxen or other anti-inflammatory medicines.",
            "Obtain a repeat chest radiograph in six weeks; the order has been placed "
            "with Blackhawk County Imaging Associates.",
            "Telephone (319) 555-0148 with any question about your medicines.",
        ]),
        ("p", "Instructions were reviewed with the patient and her son, Daniel R. "
              "Whitfield, who verbalized understanding by teach-back."),
        ("sig", "Harold T. Nakamura, MD  —  Attending Physician  —  "
                "04/13/2018 11:47"),
    ])

    assert len(P) == 20, f"printed document has {len(P)} pages"
    return P


# --------------------------------------------------------------------------
# HANDWRITTEN DOCUMENT - 20 pages of an old ward chart
# --------------------------------------------------------------------------
# Blocks: ("t", text) title, ("l", text) line, ("b",) blank, ("hr",) rule,
# ("kv", label, value), ("p", text) wrapped paragraph, ("sig", text)

def handwritten_pages():
    P = []

    # 1. Chart cover
    P.append([
        ("t", "PROVIDENCE MERCY HOSPITAL"),
        ("l", "Fall River, Massachusetts"),
        ("b",), ("hr",), ("b",),
        ("t", "IN-PATIENT CLINICAL RECORD"),
        ("b",),
        ("kv", "Name", "Brennan, Arthur Leonard"),
        ("kv", "Unit No.", "22-84-016"),
        ("kv", "Ward", "C  -  Men's Medical,  Bed 11"),
        ("kv", "Age", "51 yrs."),
        ("kv", "Born", "11 Sept 1919  -  New Bedford, Mass."),
        ("kv", "Soc. Sec.", "327-56-4188"),
        ("kv", "Address", "58 Marlborough Row"),
        ("kv", "", "Fall River, Mass. 02720"),
        ("kv", "Telephone", "OS 4-7719"),
        ("kv", "Occupation", "Loom fixer, Bourne Mills (28 yrs.)"),
        ("kv", "Married", "Yes - wife Mrs. Edith Brennan"),
        ("kv", "Religion", "Roman Catholic - Fr. Cornelius Doyle notified"),
        ("b",),
        ("kv", "Admitted", "17 Jan 1971,  11.40 a.m."),
        ("kv", "Admitting Dr.", "R. W. Ashcroft, M.D."),
        ("kv", "Referred by", "J. P. Mulcahy, M.D. - Pleasant St. office"),
        ("kv", "Adm. Diagnosis", "Bleeding peptic ulcer? - anaemia"),
        ("b",),
        ("kv", "Discharged", "2 Feb 1971"),
        ("kv", "Final Diagnosis", "Chronic duodenal ulcer with haemorrhage;"),
        ("kv", "", "iron deficiency anaemia; chronic bronchitis"),
        ("b",), ("hr",), ("b",),
        ("l", "Next of kin:  Mrs. Edith Brennan (wife), same address."),
        ("l", "Insurance:  Blue Cross of Mass.  No. 41-9927-B"),
        ("l", "Employer's certificate on file - Bourne Mills, personnel dept."),
    ])

    # 2. Admission note
    P.append([
        ("t", "ADMISSION NOTE"),
        ("l", "17 Jan 1971    Ward C"),
        ("hr",), ("b",),
        ("p", "This 51 year old married white male loom fixer is admitted at "
              "11.40 a.m. complaining of black tarry stools for 4 days and "
              "increasing weakness. Referred from the office of Dr. J. P. Mulcahy "
              "who found the haemoglobin 7.2 gm."),
        ("b",),
        ("p", "Patient states he has had burning epigastric pain for about 3 years, "
              "relieved by milk and by soda. Pain wakes him at 2 a.m. most nights. "
              "He has been taking soda powders from the chemist and, latterly, "
              "aspirin for a bad shoulder - as many as 12 tablets a day."),
        ("b",),
        ("p", "Four days ago he passed a large black stool, and again the following "
              "morning. He felt faint at the loom on Friday and was sent home by the "
              "foreman. No frank haematemesis. No vomiting. Appetite poor for a "
              "fortnight. Weight down about 10 lb."),
        ("b",),
        ("p", "Past history: Pneumonia 1943 while in the Army. Appendix out 1951, "
              "Union Hospital. Smokes 1 1/2 packs Camels daily since age 17. Beer "
              "on Saturdays. No known drug allergy - penicillin given 1943 without "
              "trouble."),
        ("b",),
        ("p", "Family: Father died 62, 'stomach trouble'. Mother living, 78, "
              "diabetic. One brother, well. Two children, both well."),
        ("b",),
        ("sig", "R. W. Ashcroft, M.D."),
    ])

    # 3. Physical examination
    P.append([
        ("t", "PHYSICAL EXAMINATION"),
        ("l", "17 Jan 1971"),
        ("hr",), ("b",),
        ("l", "T. 98.6    P. 108    R. 22    B.P. 104/68 lying"),
        ("l", "                                  86/56 sitting"),
        ("l", "Wt. 148 lb.    Ht. 5 ft. 9 in."),
        ("b",),
        ("l", "General:  Pale, thin man, looks older than stated age."),
        ("l", "          Alert, co-operative, in no acute distress."),
        ("l", "Skin:     Pale, cool. No jaundice, no spider naevi."),
        ("l", "Head:     Normal. Conjunctivae very pale."),
        ("l", "Mouth:    Poor dentition, several teeth missing."),
        ("l", "          Tongue smooth and red."),
        ("l", "Neck:     Supple. No nodes. Thyroid not enlarged."),
        ("l", "          Neck veins flat."),
        ("l", "Chest:    Emphysematous. Scattered rhonchi both bases,"),
        ("l", "          clearing with cough. No rales."),
        ("l", "Heart:    Rapid, regular. Soft systolic murmur at apex,"),
        ("l", "          grade 1/6, thought haemic. No gallop."),
        ("l", "Abdomen:  Soft. Tenderness in epigastrium without"),
        ("l", "          guarding or rebound. Liver 1 finger below"),
        ("l", "          costal margin, smooth. Spleen not felt."),
        ("l", "          Old appendix scar, well healed."),
        ("l", "Rectal:   Black tarry stool on glove. Guaiac ++++."),
        ("l", "          Prostate 1+, smooth."),
        ("l", "Extrem.:  No oedema, no clubbing. Nails brittle."),
        ("l", "C.N.S.:   Cranial nerves intact. Reflexes 2+ and equal."),
        ("l", "          No pathological reflexes."),
        ("b",),
        ("l", "Impression: 1. Upper G.I. haemorrhage, probably duodenal"),
        ("l", "               ulcer."),
        ("l", "            2. Iron deficiency anaemia, severe."),
        ("l", "            3. Chronic bronchitis."),
        ("b",),
        ("sig", "R. W. Ashcroft, M.D."),
    ])

    # 4. Orders
    P.append([
        ("t", "PHYSICIAN'S ORDERS"),
        ("hr",), ("b",),
        ("l", "17 Jan 1971  11.55 a.m."),
        ("l", "  1.  Admit Ward C, bed 11.  Complete bed rest."),
        ("l", "  2.  Sippy diet, hourly milk & cream 6 a.m. - 10 p.m."),
        ("l", "  3.  Type & cross-match 4 units whole blood."),
        ("l", "  4.  Hgb, Hct, W.B.C. & diff. stat and q. 6 h."),
        ("l", "  5.  B.U.N., electrolytes, prothrombin time stat."),
        ("l", "  6.  Stool for occult blood each specimen."),
        ("l", "  7.  Levine tube - iced saline lavage until clear."),
        ("l", "  8.  I.V. 5% D/W 1000 cc. q. 8 h."),
        ("l", "  9.  Vital signs q. 15 min. x 4, then q. 1 h."),
        ("l", " 10.  Aluminium hydroxide gel 30 cc. q. 1 h. while awake."),
        ("l", " 11.  Phenobarbital gr. 1/2 t.i.d."),
        ("l", " 12.  NO ASPIRIN.  NO SALICYLATES OF ANY KIND."),
        ("l", " 13.  Notify H.O. if B.P. systolic under 90."),
        ("sig", "R. W. Ashcroft, M.D."),
        ("b",),
        ("l", "17 Jan 1971  6.10 p.m."),
        ("l", " 14.  Transfuse 2 units whole blood now, slowly."),
        ("l", " 15.  Benadryl 50 mg. I.M. before transfusion."),
        ("l", " 16.  Hgb. in a.m."),
        ("sig", "H. Steinmetz, M.D."),
        ("b",),
        ("l", "18 Jan 1971  8.30 a.m."),
        ("l", " 17.  Upper G.I. series when bleeding stopped 24 h."),
        ("l", " 18.  Ferrous sulphate gr. 5 t.i.d. p.c. when taking p.o."),
        ("l", " 19.  Continue antacid hourly."),
        ("l", " 20.  Out of bed to commode only."),
        ("sig", "R. W. Ashcroft, M.D."),
    ])

    # 5. Nurses' admission
    P.append([
        ("t", "NURSES' NOTES"),
        ("hr",), ("b",),
        ("l", "17 Jan 71   12.15 p.m."),
        ("p", "Admitted to bed 11 per wheelchair from admitting office. "
              "Skin pale and moist. States he feels 'washed out'. "
              "Side rails up. Bell within reach. Orientation to ward given "
              "to patient and to wife."),
        ("sig", "Sr. M. Bernadette, R.N."),
        ("b",),
        ("l", "17 Jan 71   1.30 p.m."),
        ("p", "Levine tube passed per Dr. Ashcroft without difficulty. "
              "Returns coffee-ground material approx. 200 cc. Iced saline "
              "lavage begun. Patient tolerated fairly well."),
        ("sig", "E. Vasquez, R.N."),
        ("b",),
        ("l", "17 Jan 71   4.00 p.m."),
        ("p", "Lavage now clear. Tube left in place to low suction. "
              "B.P. 100/64. Pulse 104. Complains of thirst - mouth care given. "
              "Wife at bedside."),
        ("sig", "E. Vasquez, R.N."),
        ("b",),
        ("l", "17 Jan 71   7.20 p.m."),
        ("p", "First unit of blood started 6.40 p.m., no reaction noted. "
              "Temp. 99.0. Patient resting quietly. Fr. Doyle visited."),
        ("sig", "Miss K. Halloran, R.N."),
        ("b",),
        ("l", "17 Jan 71   11.00 p.m."),
        ("p", "Second unit completed 10.50 p.m. without incident. Slept in "
              "short naps. No further tarry stool this shift."),
        ("sig", "Miss K. Halloran, R.N."),
    ])

    # 6-13. Progress notes
    prog = [
        ("18 Jan 1971", [
            ("p", "Feels somewhat stronger this morning. No further melaena "
                  "overnight. Levine tube drainage clear yellow, 340 cc. in "
                  "12 hours."),
            ("l", "  T. 99.2   P. 96   B.P. 112/70"),
            ("l", "  Hgb. 9.4 gm.  (was 7.2 on adm.)"),
            ("l", "  Hct. 29%   W.B.C. 11,200"),
            ("p", "Abdomen soft, epigastric tenderness less marked. Bowel "
                  "sounds active. Chest clear except for occasional rhonchus."),
            ("p", "Imp. Bleeding appears to have stopped. Will continue "
                  "conservative management. Tube may come out this evening "
                  "if drainage stays clear."),
        ], "R. W. Ashcroft, M.D."),
        ("19 Jan 1971", [
            ("p", "Levine tube removed 8 p.m. yesterday. Took milk and cream "
                  "overnight without vomiting. Slept well. Asks for a cigarette "
                  "- explained why not."),
            ("l", "  T. 98.8   P. 88   B.P. 118/74"),
            ("l", "  Hgb. 9.8 gm.   Hct. 30%"),
            ("l", "  Stool guaiac ++  (was ++++)"),
            ("p", "Ferrous sulphate begun. Warned patient of black stools from "
                  "iron so that he is not alarmed, and so that we are not "
                  "misled."),
            ("p", "Upper G.I. series ordered for tomorrow a.m. if he remains "
                  "stable through tonight."),
        ], "R. W. Ashcroft, M.D."),
        ("20 Jan 1971", [
            ("p", "Upper G.I. series done this morning by Dr. Okamura. Report "
                  "on chart: large deformed duodenal cap with a persistent "
                  "niche on the lesser curve, consistent with chronic ulcer. "
                  "No gastric lesion. No obstruction."),
            ("l", "  T. 98.6   P. 84   B.P. 120/76"),
            ("l", "  Hgb. 10.2 gm."),
            ("p", "Patient much brighter. Ate soft diet at noon. No pain since "
                  "admission apart from mild epigastric soreness."),
            ("p", "Discussed findings with patient and with Mrs. Brennan. "
                  "Explained that surgery is not required at this time but that "
                  "he must give up aspirin altogether and cut down the "
                  "cigarettes. He agreed to try."),
        ], "R. W. Ashcroft, M.D."),
        ("21 Jan 1971", [
            ("p", "Quiet night. No pain, no melaena. Bowels moved - stool dark "
                  "from iron, guaiac now +."),
            ("l", "  T. 98.4   P. 80   B.P. 122/78"),
            ("l", "  Hgb. 10.6 gm.   Hct. 33%"),
            ("p", "Chest: a few coarse rhonchi at both bases in the morning, "
                  "clearing after he coughs. Sputum thick and grey. Chest film "
                  "ordered - query old scarring from the '43 pneumonia."),
            ("p", "Ambulating in room. Tolerating six small feedings."),
        ], "L. Cavanaugh, M.D."),
        ("22 Jan 1971", [
            ("p", "Chest film reported by Dr. Okamura: increased bronchovascular "
                  "markings, hyperinflation, old fibrotic changes right upper "
                  "lobe. No active infiltrate. Heart normal size."),
            ("l", "  T. 98.6   P. 78   B.P. 124/78"),
            ("p", "Cough productive of grey sputum in the mornings only. This "
                  "is his usual winter pattern for the past 5 years and is "
                  "clearly chronic bronchitis of the smoker."),
            ("p", "Walked the length of the corridor twice without distress. "
                  "Appetite good. No epigastric pain."),
        ], "L. Cavanaugh, M.D."),
        ("23 Jan 1971", [
            ("p", "Uneventful. Complains only of being kept in bed too long "
                  "and of the hospital food, which I take as a good sign."),
            ("l", "  T. 98.4   P. 76   B.P. 124/80   Wt. 150 lb."),
            ("l", "  Hgb. 11.1 gm.   Hct. 35%   Retic. 4.2%"),
            ("p", "Good reticulocyte response to iron. Marrow evidently "
                  "responding well. Continue ferrous sulphate for at least "
                  "6 months after the haemoglobin is normal, to fill the "
                  "stores."),
        ], "R. W. Ashcroft, M.D."),
        ("24 Jan 1971", [
            ("p", "Seen with Dr. Mulcahy, who came in to see the patient. "
                  "Agreed on plan for medical management with strict avoidance "
                  "of salicylates."),
            ("l", "  T. 98.6   P. 78   B.P. 126/80"),
            ("p", "Sunday. Family visited, patient in good spirits. Ate all of "
                  "his dinner. Slept in the chair for two hours in the "
                  "afternoon."),
            ("p", "Plan: gastroenterology opinion tomorrow re. long-term "
                  "management, then home about the end of the week if all "
                  "remains well."),
        ], "L. Cavanaugh, M.D."),
        ("26 Jan 1971", [
            ("p", "Consultation note from Dr. Pemberton on chart. Agrees with "
                  "medical management; no indication for operation in the "
                  "absence of obstruction, perforation or continued bleeding."),
            ("l", "  T. 98.4   P. 76   B.P. 124/78"),
            ("l", "  Hgb. 11.6 gm.   Hct. 36%"),
            ("p", "Stool guaiac negative x 3 specimens. This is the first "
                  "negative series since admission."),
            ("p", "Diet advanced to bland, six feedings. Antacid reduced to "
                  "1 and 3 hours after meals and at bedtime."),
        ], "R. W. Ashcroft, M.D."),
    ]
    for date, body, sig in prog:
        blocks = [("t", "PROGRESS NOTES"), ("l", date + "    Ward C   Bed 11"),
                  ("hr",), ("b",)]
        for b in body:
            blocks.append(b)
            blocks.append(("b",))
        blocks.append(("sig", sig))
        P.append(blocks)

    # 14. Consultation
    P.append([
        ("t", "CONSULTATION"),
        ("l", "25 Jan 1971    Requested by Dr. R. W. Ashcroft"),
        ("hr",), ("b",),
        ("l", "Re:  Brennan, Arthur L.    Unit No. 22-84-016"),
        ("b",),
        ("p", "Thank you for asking me to see this pleasant 51 year old mill "
              "worker with a chronic duodenal ulcer which bled on 13-16 Jan."),
        ("b",),
        ("p", "I have reviewed the films with Dr. Okamura. The cap is grossly "
              "deformed and there is a constant niche. The changes are those "
              "of long-standing disease. There is no evidence of pyloric "
              "obstruction: the stomach emptied well at 6 hours."),
        ("b",),
        ("p", "The haemorrhage stopped without operation and he has had no "
              "further bleeding for 9 days. In my opinion there is no present "
              "indication for surgery. Operation would be indicated for "
              "recurrent severe haemorrhage, perforation, obstruction, or "
              "intractable pain."),
        ("b",),
        ("l", "Recommendations:"),
        ("l", "  1.  Bland diet, six small feedings."),
        ("l", "  2.  Antacid 1 and 3 hours after meals and h.s."),
        ("l", "  3.  Absolute prohibition of aspirin and of the"),
        ("l", "      proprietary powders he has been using."),
        ("l", "  4.  Stop smoking, or reduce to under half a pack."),
        ("l", "  5.  Continue iron for 6 months."),
        ("l", "  6.  Repeat upper G.I. in 3 months."),
        ("l", "  7.  Office follow-up with Dr. Mulcahy in 2 weeks."),
        ("b",),
        ("p", "I shall be glad to see him again if any question arises."),
        ("b",),
        ("sig", "G. Pemberton, M.D."),
    ])

    # 15. Graphic / vitals sheet
    P.append([
        ("t", "GRAPHIC AND CLINICAL RECORD"),
        ("l", "Brennan, Arthur L.        Unit No. 22-84-016"),
        ("hr",), ("b",),
        ("l", "Date      T.      P.    R.    B.P.      Wt."),
        ("l", "17 Jan   98.6    108   22   104/68    148"),
        ("l", "18 Jan   99.2     96   20   112/70     --"),
        ("l", "19 Jan   98.8     88   20   118/74     --"),
        ("l", "20 Jan   98.6     84   18   120/76    148"),
        ("l", "21 Jan   98.4     80   18   122/78     --"),
        ("l", "22 Jan   98.6     78   18   124/78     --"),
        ("l", "23 Jan   98.4     76   18   124/80    150"),
        ("l", "24 Jan   98.6     78   18   126/80     --"),
        ("l", "25 Jan   98.4     76   18   124/78     --"),
        ("l", "26 Jan   98.4     76   18   124/78    151"),
        ("l", "27 Jan   98.6     74   18   126/80     --"),
        ("l", "29 Jan   98.4     74   16   128/80    152"),
        ("l", "1 Feb    98.6     72   16   126/78    153"),
        ("b",),
        ("l", "Intake and Output"),
        ("l", "Date     Oral    I.V.    Blood    Urine   Suction"),
        ("l", "17 Jan    200    2000     1000      750     540"),
        ("l", "18 Jan    900    1000        0     1150     340"),
        ("l", "19 Jan   1600     500        0     1400       0"),
        ("l", "20 Jan   1900       0        0     1650       0"),
        ("l", "21 Jan   2000       0        0     1800       0"),
        ("b",),
        ("l", "Bowels:  17th - tarry x 1;  18th - none;"),
        ("l", "         19th - dark x 1;  20th - dark x 1;"),
        ("l", "         21st onward - normal colour with iron."),
        ("b",),
        ("l", "Sputum:  grey, mornings, moderate amount."),
        ("l", "Sleep:   good from 19 Jan, no sedation required after"),
        ("l", "         the second night."),
    ])

    # 16. Laboratory
    P.append([
        ("t", "LABORATORY REPORTS"),
        ("l", "Brennan, Arthur L.     Unit No. 22-84-016     Ward C"),
        ("hr",), ("b",),
        ("l", "Haematology"),
        ("l", "Date     Hgb.    Hct.   W.B.C.   Retic.   Plat."),
        ("l", "17 Jan   7.2 gm   22%   13,400    1.1%    340,000"),
        ("l", "18 Jan   9.4      29%   11,200    2.4%      --"),
        ("l", "19 Jan   9.8      30%    9,800    3.6%      --"),
        ("l", "21 Jan  10.6      33%    8,400    4.0%      --"),
        ("l", "23 Jan  11.1      35%    7,900    4.2%    310,000"),
        ("l", "26 Jan  11.6      36%    7,200    2.8%      --"),
        ("l", "1 Feb   12.4      38%    6,800    1.6%      --"),
        ("b",),
        ("l", "Differential 17 Jan:  polys 74, bands 6, lymphs 16,"),
        ("l", "                      monos 3, eos 1."),
        ("l", "Smear:  hypochromic, microcytic. Anisocytosis 2+."),
        ("b",),
        ("l", "Chemistry"),
        ("l", "  B.U.N.        17 Jan  38 mg%    19 Jan  18 mg%"),
        ("l", "  Sodium        17 Jan  138 mEq.  Potassium  3.8 mEq."),
        ("l", "  Chloride      17 Jan  101 mEq.  CO2  26 mEq."),
        ("l", "  Blood sugar   17 Jan  104 mg%"),
        ("l", "  Serum iron    19 Jan  22 ug%   (low)"),
        ("l", "  T.I.B.C.      19 Jan  486 ug%  (high)"),
        ("l", "  Total protein 19 Jan  6.2 gm%  Albumin 3.6"),
        ("l", "  Prothrombin   17 Jan  88% of control"),
        ("b",),
        ("l", "Serology:   V.D.R.L. non-reactive."),
        ("l", "Urine:      Sp. gr. 1.024, alb. neg., sugar neg.,"),
        ("l", "            micro. 1-2 W.B.C., no casts."),
        ("l", "Stool:      Guaiac ++++ (17th), ++ (19th), + (21st),"),
        ("l", "            negative x 3 (24-26 Jan)."),
        ("l", "Blood group:  O positive.  Cross-match compatible."),
        ("b",),
        ("sig", "A. Chowdhury, M.D.,  Path."),
    ])

    # 17. X-ray
    P.append([
        ("t", "X-RAY DEPARTMENT REPORT"),
        ("hr",), ("b",),
        ("l", "Brennan, Arthur L.      Unit No. 22-84-016"),
        ("l", "Examination:  Upper gastro-intestinal series"),
        ("l", "Date:  20 Jan 1971      Film No. 71-4418"),
        ("b",),
        ("p", "The oesophagus is normal in calibre and empties freely. The "
              "stomach is of average tone with normal rugal pattern. No "
              "filling defect and no gastric ulcer crater is demonstrated."),
        ("b",),
        ("p", "The duodenal cap is markedly deformed and irritable, filling "
              "poorly and emptying at once. On the lesser curvature there is a "
              "small collection of barium which persists on several films and "
              "which I regard as an active ulcer niche, approximately 6 mm."),
        ("b",),
        ("p", "The remainder of the duodenal sweep is normal. There is no "
              "evidence of gastric retention; the stomach was empty at the six "
              "hour film."),
        ("b",),
        ("l", "CONCLUSION:  Chronic duodenal ulcer with active niche."),
        ("l", "             No obstruction. No gastric lesion."),
        ("b",),
        ("sig", "T. Okamura, M.D."),
        ("b",), ("hr",), ("b",),
        ("l", "Examination:  Chest, P.A. and lateral"),
        ("l", "Date:  22 Jan 1971      Film No. 71-4502"),
        ("b",),
        ("p", "Hyperinflation with flattening of the diaphragms and increased "
              "bronchovascular markings. Old fibrotic and pleural changes at "
              "the right apex, unchanged from the film of 1963. No active "
              "infiltrate, no effusion. Heart within normal limits."),
        ("b",),
        ("l", "CONCLUSION:  Chronic bronchitis and emphysema."),
        ("l", "             Old healed disease, right upper lobe."),
        ("b",),
        ("sig", "T. Okamura, M.D."),
    ])

    # 18. Nurses' notes late
    P.append([
        ("t", "NURSES' NOTES  (continued)"),
        ("hr",), ("b",),
        ("l", "27 Jan 71   7.00 a.m."),
        ("p", "Slept through the night. No complaint of pain. Took all of "
              "breakfast. Walked to the sun room and back unaided."),
        ("sig", "Sr. M. Bernadette, R.N."),
        ("b",),
        ("l", "28 Jan 71   2.00 p.m."),
        ("p", "Wife brought in street clothes. Patient anxious to go home. "
              "Explained he must wait for the doctor's word. Diet instruction "
              "sheet given and gone over with both of them."),
        ("sig", "E. Vasquez, R.N."),
        ("b",),
        ("l", "29 Jan 71   9.30 a.m."),
        ("p", "Dietitian, Miss Farrow, spent 40 minutes with patient and wife "
              "on the six-feeding bland diet. Wife has written out a week of "
              "menus. Both appear to understand."),
        ("sig", "Sr. M. Bernadette, R.N."),
        ("b",),
        ("l", "31 Jan 71   8.00 p.m."),
        ("p", "Quiet day. Bowels moved, normal colour. No pain. Smoked one "
              "cigarette in the sun room - reminded of the doctor's advice, "
              "says he is down from 30 a day to 8."),
        ("sig", "Miss K. Halloran, R.N."),
        ("b",),
        ("l", "2 Feb 71   10.15 a.m."),
        ("p", "Discharged to home in the care of his wife. Prescriptions and "
              "diet sheet given. Valuables returned from the safe and signed "
              "for. Left the ward by wheelchair at 10.40 a.m."),
        ("sig", "E. Vasquez, R.N."),
    ])

    # 19. Discharge note
    P.append([
        ("t", "DISCHARGE SUMMARY"),
        ("l", "2 Feb 1971"),
        ("hr",), ("b",),
        ("l", "Brennan, Arthur Leonard      Unit No. 22-84-016"),
        ("l", "Admitted 17 Jan 1971.   Discharged 2 Feb 1971.   16 days."),
        ("b",),
        ("l", "FINAL DIAGNOSES:"),
        ("l", "  1.  Chronic duodenal ulcer with haemorrhage."),
        ("l", "  2.  Iron deficiency anaemia, secondary."),
        ("l", "  3.  Chronic bronchitis and emphysema."),
        ("l", "  4.  Salicylate ingestion, excessive."),
        ("b",),
        ("p", "This 51 year old loom fixer entered with a 4 day history of "
              "melaena and a haemoglobin of 7.2 gm. He was treated with bed "
              "rest, gastric lavage, hourly antacid, and 2 units of whole "
              "blood on the day of admission. Bleeding ceased within 24 hours "
              "and did not recur."),
        ("b",),
        ("p", "Upper G.I. series on 20 Jan showed a deformed duodenal cap with "
              "an active niche. Dr. Pemberton saw him in consultation on 25 "
              "Jan and advised against operation. Stools became guaiac "
              "negative on 24 Jan and remained so."),
        ("b",),
        ("p", "The haemoglobin rose steadily on oral iron to 12.4 gm at "
              "discharge with a good reticulocyte response. He gained 5 lb. "
              "and was ambulant and free of pain for the last ten days of his "
              "stay."),
        ("b",),
        ("p", "The importance of avoiding aspirin was impressed upon him "
              "repeatedly, this being in all likelihood the cause of the "
              "haemorrhage."),
        ("b",),
        ("sig", "R. W. Ashcroft, M.D."),
    ])

    # 20. Discharge instructions
    P.append([
        ("t", "DISCHARGE INSTRUCTIONS"),
        ("l", "Given to patient and wife, 2 Feb 1971"),
        ("hr",), ("b",),
        ("l", "Patient:  Mr. Arthur L. Brennan"),
        ("l", "          58 Marlborough Row, Fall River, Mass."),
        ("l", "          Telephone OS 4-7719"),
        ("b",),
        ("l", "MEDICINES:"),
        ("l", "  Ferrous sulphate gr. 5 -- three times a day after"),
        ("l", "    meals. Continue six months. Will darken the stool."),
        ("l", "  Aluminium hydroxide gel 30 cc. -- one hour and three"),
        ("l", "    hours after each meal and at bedtime."),
        ("l", "  Phenobarbital gr. 1/2 -- at bedtime if restless."),
        ("b",),
        ("l", "NO ASPIRIN.  NO BUFFERIN, ANACIN, ALKA-SELTZER OR ANY"),
        ("l", "POWDER OR TABLET FOR HEADACHE WITHOUT ASKING THE DOCTOR."),
        ("l", "For pain use only the tablets Dr. Mulcahy prescribes."),
        ("b",),
        ("l", "DIET:  Bland, six small feedings, per the sheet given."),
        ("l", "       No fried food, no spices, no alcohol, no coffee."),
        ("l", "       Milk between meals."),
        ("b",),
        ("l", "SMOKING:  Cut down to under half a pack. Better none."),
        ("b",),
        ("l", "WORK:  May return to Bourne Mills 1 March 1971, light"),
        ("l", "       duty for the first two weeks. Certificate given"),
        ("l", "       to Mrs. Brennan for the personnel department."),
        ("b",),
        ("l", "CALL THE DOCTOR AT ONCE for black stools, vomiting of"),
        ("l", "blood or coffee-ground material, severe stomach pain,"),
        ("l", "faintness or weakness."),
        ("b",),
        ("l", "RETURN:  Office of Dr. J. P. Mulcahy, 16 Feb 1971, 2 p.m."),
        ("l", "         Repeat X-ray about 20 April 1971."),
        ("b",),
        ("sig", "R. W. Ashcroft, M.D."),
        ("l", "Received and understood:   Edith Brennan  (Mrs.)"),
    ])

    assert len(P) == 20, f"handwritten document has {len(P)} pages"
    return P
