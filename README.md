## 💻 Beginner's Guide: How to Run This Script

This section will walk you through setting up Python on your computer and running the generator for the first time.

### **Step 1: Install Python on Your Computer**
Before running the script, you need the Python "engine" installed.

1.  **Download:** Go to [python.org](https://www.python.org/downloads/) and click the button to download the latest version for Windows or Mac.
2.  **Install:** Open the downloaded file. 
3.  **CRITICAL:** On the first install screen, check the box that says **"Add Python to PATH"**. If you skip this, the script won't work in the next steps.
4.  **Verify:** Open your computer's **Terminal** (Mac) or **Command Prompt** (Windows) and type `python --version`. If it returns a number (e.g., Python 3.12.x), you are ready.

---

### **Step 2: Download This Project from GitHub**
Since you are new to GitHub, the easiest way to get these files is to download them as a folder:

1.  On this GitHub page, click the green **"<> Code"** button near the top right.
2.  Select **"Download ZIP"**.
3.  Find the file in your Downloads folder and **Extract (Unzip)** it to a folder on your Desktop.

---

### **Step 3: Install the "Requirements"**
This script relies on special tools to read websites. You need to install these once:

1.  Open your **Terminal** or **Command Prompt**.
2.  Type `cd ` followed by a space, then drag the folder you just unzipped into the terminal window. Press **Enter**.
3.  Type the following command and press **Enter**:
    ```bash
    pip install -r requirements.txt
    ```
4.  Wait for the text to stop scrolling; this installs all necessary libraries.

---

### **Step 4: Configure Your URLs**
You need to tell the script which blog posts to scan.

1.  Open the folder and right-click `blog_schema_builder.py`. Choose **"Open with..."** and select **Notepad** or any text editor.
2.  Look for the section titled `URLS_TO_PROCESS`.
3.  Replace the example URLs with the ones you want to process. Ensure you follow the format (specifically the commas at the end of lines).
4.  **Save** the file and close it.

---

### **Step 5: Run the Script**
Now, let's generate the schema:

1.  Go back to your **Terminal/Command Prompt** (ensure you are still in the project folder).
2.  Type the following and press **Enter**:
    ```bash
    python blog_schema_builder.py
    ```
3.  The script will start "Fetching HTML" and "Extracting metadata."
4.  Once finished, open the newly created **`output`** folder in your project directory. Your schema code will be waiting there in `.txt` files.

---

### **Troubleshooting Tips**
* **"Python is not recognized":** This means you forgot to check the "Add to PATH" box during installation. Uninstall Python and reinstall it, making sure that box is checked.
* **Missing API Key:** If you want the script to write FAQ answers automatically, you must add a `GEMINI_API_KEY` to a `.env` file. If you don't have one, the script will still work but will use the text found on the page instead.
