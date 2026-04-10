---
title: "An Exploratory Analysis of Errors in and Relationship between Chromatography Database Calculations"
authors: "Ash Baghai"
date_published: "August 2024"
date_summarized: "2026-04-10"
source: "Abaghai_An Exploratory Analysis of Errors in and Relationship between Chromatography Database Calculations.pdf"
tags: [journal-article, summary]
---

# An Exploratory Analysis of Errors in and Relationship between Chromatography Database Calculations

## Metadata
- **Author(s):** Ash Baghai
- **Date Published:** August 2024
- **Date Summarized:** 2026-04-10
- **Source File:** Abaghai_An Exploratory Analysis of Errors in and Relationship between Chromatography Database Calculations.pdf
- **Pages:** 11

---

## Abstract / Overview
Accurate chemical analys es are essential in pharmaceutical development, and Empower, a leading Chromatography Data System (CDS), plays a crucial role in this process. It is an application used to conduct liquid chromatography analysis of drug compounds, relying on specialized calculations called custom fields. However, as methods evolve, these custom fields can become outdated, and managing them becomes challenging due to the complex interdependencies between fields. To address this issue, a Python program has been developed that analyzes custom field data from Empower. The program works with a specific tab-delimited, Empower text file export, which contains all relevant custom field information. The program's two main goals are to detect errors in custom fields and analyze how they relate to one another, by virtue of their references in one another’s formulas. By identifying these connections, the program helps streamline the process of correcting , maintaining, and updating custom fields, keeping them in line with current scientific and regulatory standards.

---

## Content Notes

### I. Introduction
   - Accurate chemical analys es are essential in pharmaceutical development, and Empower, a leading Chromatography Data System (CDS), plays a crucial role in this process.
   - To address this issue, a Python program has been developed that analyzes custom field data from Empower.
   - By identifying these connections, the program helps streamline the process of correcting , maintaining, and updating custom fields, keeping them in line with current scientific and regulatory standards.

### II. Questions
   A. **1. Can naming and formula  errors be detected among custom fields within the Empower**
      - Database? 2.
      - How can the impact of custom field (CFs) alterations on other fields be determined ? a) More specifically , what relationships exist between custom fields based on their references within formulas?

### III. Github Repo
   - https://github.com/UC -Berkeley -I-School/Project2_Ash_Baghai

### IV. Data Source
   - Chromatography Database Data Source The Data file is sourced from an Empower Chromatography Database .
   - Description The main dataset is a tab- delimited text file, "CF_Data_File_Project2.txt The data file contains relevant data columns for custom fields associated with experimental chromatography studies.
   - Primary Data columns of Interest Column Name: “customfieldname ” and “formula ” Data type: String Object Size 336KB 2883 rows, 8 columns Data Fields Desicription Value Example(s) project_name The name of a project directory path within Empower where chromatographic methods, custom fields, experimental raw data and processed results would be located. 20XX_Q3\GxP_20XX_Q3\ WC_20XX_Q3\ZY8122_20XX_Q3 customfieldname The name of particular chromatographic calculations ABS_Assay_Diff field_type The experiment category which the custom field’s data relates to Sample, Sample Set, Peak, or Component type The data format of the custom field’s output Real(0.0), Text, or Enum source the custom fields output source Keyboard or Calculated formula The equation for a custom field (SAME.%..MAX(Weight_Percent_As_Is)) - (SAME.%..MIN(Weight_Percent_As_Is))

### V. Data Cleaning
   - The analysis used a dataset exported from an Empower Database as a tab- delimited text file, serving as the primary input.
   - The data type for the columns of interest, “customfieldname” and “formula” matched expectation, String objects.
   - Confirmation of Data type

### VI. Assumptions
   - Ignore Simultaneous Errors in CF Naming and Formulas Simultaneous errors in custom field (CF) naming and formulas were not evaluated due to their low probability and the need for a feature outside the current program scope.
   - Evaluation of CF Relationships Ignores Mathematical Operations The analysis considered CF relationships based on their occurrence in formulas but did not factor in the associated mathematical operations.
   - Dropped columns deemed unessential “#” and “Cfield Id” columns were dropped as they were designated as unessential

### VII. Error Detection Analysis
   - I began with a basic exploratory data analysis to identify any missing or incorrect values.
   - Basic Exploratory Data Analysis Workflow Handling Empty Formulas Custom fields relying on manual inputs (“Keyboard” source desingations) are expected to have empty formulas , which is not necessarily the case for those with "Calculated ” source designations.
   - This process included removing duplicate data since custom fields are often
   - reused across projects, as shown in the top two tables of Error!
   - Not a valid bookmark self - reference. .
   - Error Detection Detected errors are boxed in red.

### VIII. Identifying Custom Field Relationships
   A. **Recursive Analysis**
      - A recursive analysis was conducted to assess how custom fields depend on one another within the dataset.
      - Table 1 summarizes the direct and nested references of custom fields in other custom field formulas, either directly or indirectly through nested references.
      - The bar graph below in
   - Figure E, shows the frequency of these references across all formulas.
   - Table 1.
   - The frequency count for direct and recursively referenced custom fields

### IX. Cluster Analysis
   - A cluster analysis, using the python NetworkX library , was conducted to identify natural groupings of custom fields based on formula similarities and weakly connected components; this signifies direct and intermediate connections .
   - Table 2.
   - Barplot of Cluster Analysis: Cluster Number vs Cluster Size

### X. Network Graph Analysis
   - A directed graph was then used to visualize network relationships within each cluster by mapping the direct and intermediate connections between nodes.
   - In contrast, the custom fields, “ Percent_Assay_Difference” and “ Weight_Percent_Dry ” are highly reliant on multiple sources for their calculations as indicated in red.
   - Custom field , Network Dependency Tree for Cluster 1
   - Note: Network Graph Analyses were carried out on all network clusters with greater than 2 nodes .
   - Only one graph is depicted here as it conveys the central insight from the analyses.
   - The remainder s are included in the appendices.

### XI. Network Centrality Analysis
   - Finally, a network centrality analysis was conducted to quantify the influence of custom fields within the network.
   - Additionally, custom fields central to the other clusters of interest are marked with asterisks, highlighting their importance within their respective clusters.
   - Network Centrality Analysis: Custom Fields vs Degree Centrality

### XII. Conclusion
   - The exploratory data analysis (EDA) successfully identified three key errors within the dataset: two naming errors and one formula error.
   - These clusters offer valuable insights for future updates, allowing for more targeted modifications within specific categories.
   - Notably: Cluster # Custom Field(s) 1 Label_Claim, Percent Assay Difference, and Weight_Percent_Dry. 2 Dilution 3 CA 7 Sys Suit These findings provide a robust framework for error correction and understanding the complex interdependencies of custom fields to guide effective Empower database management and updates.

### XIII. Appendix
   - Figurere A1.
   - Custom field , Network Dependency Tree for Cluster 2 Figurere A2.
   - Custom field , Network Dependency Tree for Cluster 3
   - Figurere A3.
   - Custom field , Network Dependency Tree for Cluster 7


---

## Key Findings & Takeaways
- The exploratory data analysis (EDA) successfully identified three key errors within the dataset: two naming errors and one formula error.
- A recursive analysis highlighted the significant reliance on four top custom fields, with the degree of dependence ranked as follows: CA > Label_Claim = Sys_Suit > Dilution.
- The cluster analysis revealed seven distinct clusters of linked custom fields.
- These clusters offer valuable insights for future updates, allowing for more targeted modifications within specific categories.
- Notably: Cluster # Custom Field(s) 1 Label_Claim, Percent Assay Difference, and Weight_Percent_Dry. 2 Dilution 3 CA 7 Sys Suit These findings provide a robust framework for error correction and understanding the complex interdependencies of custom fields to guide effective Empower database management and updates.

---

## Methodology
- Chromatography Database Data Source The Data file is sourced from an Empower Chromatography Database .
- Description The main dataset is a tab- delimited text file, "CF_Data_File_Project2.txt The data file contains relevant data columns for custom fields associated with experimental chromatography studies.
- Primary Data columns of Interest Column Name: “customfieldname ” and “formula ” Data type: String Object Size 336KB 2883 rows, 8 columns Data Fields Desicription Value Example(s) project_name The name of a project directory path within Empower where chromatographic methods, custom fields, experimental raw data and processed results would be located. 20XX_Q3\GxP_20XX_Q3\ WC_20XX_Q3\ZY8122_20XX_Q3 customfieldname The name of particular chromatographic calculations ABS_Assay_Diff field_type The experiment category which the custom field’s data relates to Sample, Sample Set, Peak, or Component type The data format of the custom field’s output Real(0.0), Text, or Enum source the custom fields output source Keyboard or Calculated formula The equation for a custom field (SAME.%..MAX(Weight_Percent_As_Is)) - (SAME.%..MIN(Weight_Percent_As_Is))
- The analysis used a dataset exported from an Empower Database as a tab- delimited text file, serving as the primary input.
- After formatting, I verified that the data columns, fields, and types were accurately represented for further analysis.
- Figure A.
- Confirmation of Data type
- A cluster analysis, using the python NetworkX library , was conducted to identify natural groupings of custom fields based on formula similarities and weakly connected components; this signifies direct and intermediate connections .
- These insights could offer guidance on which custom fields to consider for similar updates based on their formula similarities.
- Cluster Analysis: number of Connected Custom Fields (Nodes) with a given cluster Clusters # Nodes CF Dependencies Cluster 1 11 Label_Claim, Residual_Solvent, Weight_Percent_Anhydrous, Other_Impurity, xSampleWeight, WaterContent, ABS_Assay_Diff, OVI, Percent_Assay_Difference, Weight_Percent_Dry, Weight_Percent_As_Is Cluster 2 7 AR_Sensitivity, CalWts, SampleWeight, Standard_Recovery, Sensitivity, Dilution, Standard_Recovery_Ninj Cluster 3 5 AVE_CorrectedAN, CA, TotalCA, CorrectedAN, TotalAreaGroup Cluster 4 2 LIMS_TRANSFER_ATTRIBUTE, xPeakTransfer Cluster 5 2 Weight_Percent_OVI, OVI_ppm Cluster 6 2 Corr_Dis_Amt, Percent_Dissolved Cluster 7 4 R_USP_Tailing, R_USP_Plates, R_USP_Resolution, Sys_Suit Figure F.

---

## References
- *No references section detected.*

---

## Personal Notes
- 
