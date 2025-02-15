import ctypes
import os
import sys
import win32com.client
import time
from concurrent.futures import ThreadPoolExecutor
from colorama import init, Fore, Back, Style
import pyfiglet
import winreg
import signal
import threading
import psutil  # To get available system RAM

# Check if the script is running as admin
def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except:
        return False

# If not admin, relaunch the script as admin
def run_as_admin():
    if sys.version_info[0] < 3:
        executable = sys.executable.encode(sys.getfilesystemencoding())
    else:
        executable = sys.executable

    ctypes.windll.shell32.ShellExecuteW(None, "runas", executable, ' '.join(sys.argv), None, 1)

# Enable or disable write protection
def set_write_protect(enable):
    reg_paths = [
        r"SOFTWARE\Policies\Microsoft\Windows\RemovableStorageDevices\{53f5630d-b6bf-11d0-94f2-00a0c91efb8b}",
        r"System\ControlSet001\Control\StorageDevicePolicies"
    ]

    try:
        # Modifying first registry path
        with winreg.CreateKey(winreg.HKEY_LOCAL_MACHINE, reg_paths[0]) as key:
            if enable:
                winreg.SetValueEx(key, "Deny_Write", 0, winreg.REG_DWORD, 1)
            else:
                winreg.DeleteValue(key, "Deny_Write")
        
        # Modifying second registry path
        with winreg.CreateKey(winreg.HKEY_LOCAL_MACHINE, reg_paths[1]) as key:
            if enable:
                winreg.SetValueEx(key, "WriteProtect", 0, winreg.REG_DWORD, 1)
            else:
                winreg.DeleteValue(key, "WriteProtect")

        return True
    except FileNotFoundError:
        return False
    except Exception as e:
        print(Fore.RED + f"Failed to modify registry: {e}")
        return False

# Handle termination or cancellation by the user to disable write protection
def cleanup_on_exit():
    print(Fore.YELLOW + "Disabling write protection...")
    if set_write_protect(False):
        print(Fore.GREEN + "USB Write-protect setting has been restored.")
        print(Fore.CYAN + "\nPlease detach and re-attach USB drives for settings to take effect.")
    else:
        print(Fore.RED + "Failed to restore write protection setting.")

# Register signal to call cleanup function when the task is canceled or interrupted
signal.signal(signal.SIGINT, lambda signum, frame: cleanup_on_exit())  # For Ctrl+C
signal.signal(signal.SIGTERM, lambda signum, frame: cleanup_on_exit())  # For external termination

# If not running as admin, re-launch as admin
if not is_admin():
    run_as_admin()
    sys.exit()

# Initialize colorama
init(autoreset=True)

def list_physical_disks():
    """List all physical disks available on the system."""
    physical_disks = []
    wmi = win32com.client.Dispatch("WbemScripting.SWbemLocator")
    service = wmi.ConnectServer(".", "root\\cimv2")
    for disk in service.ExecQuery("SELECT DeviceID, Model FROM Win32_DiskDrive"):
        physical_disks.append((disk.DeviceID, disk.Model))
    return physical_disks

def get_disk_size(disk):
    """Get the size of the physical disk in bytes."""
    wmi = win32com.client.Dispatch("WbemScripting.SWbemLocator")
    service = wmi.ConnectServer(".", "root\\cimv2")
    for d in service.ExecQuery("SELECT Size, DeviceID FROM Win32_DiskDrive"):
        if d.DeviceID == disk:
            return int(d.Size)
    return 0

def get_ram_size():
    """Get the system's available RAM in bytes."""
    return psutil.virtual_memory().available

def read_physical_disk(disk, block_size, offset):
    """Read a block of specified size from the physical disk at the given offset."""
    handle = ctypes.windll.kernel32.CreateFileW(
        f"\\\\.\\{disk}",
        0x80000000,  # GENERIC_READ
        0x00000001 | 0x00000002,  # FILE_SHARE_READ | FILE_SHARE_WRITE
        None,
        0x00000003,  # OPEN_EXISTING
        0,
        None
    )

    if handle == ctypes.c_void_p(-1).value:
        raise Exception(f"Failed to open disk {disk}")

    # Move the file pointer to the correct position using SetFilePointerEx
    offset_high = ctypes.c_long(offset >> 32)
    offset_low = ctypes.c_long(offset & 0xFFFFFFFF)
    result = ctypes.windll.kernel32.SetFilePointerEx(handle, offset_low, ctypes.byref(offset_high), 0)
    if not result:
        ctypes.windll.kernel32.CloseHandle(handle)
        raise Exception(f"Failed to set file pointer for disk {disk}")

    read_buffer = ctypes.create_string_buffer(block_size)
    read = ctypes.c_ulong(0)

    success = ctypes.windll.kernel32.ReadFile(
        handle,
        read_buffer,
        block_size,
        ctypes.byref(read),
        None
    )

    ctypes.windll.kernel32.CloseHandle(handle)

    if not success or read.value == 0:
        return None, 0

    return read_buffer.raw[:read.value], read.value

def format_speed(bytes_per_second):
    """Format the speed to be human-readable."""
    units = ["B/s", "KB/s", "MB/s", "GB/s"]
    speed = bytes_per_second
    unit = units[0]
    for u in units:
        if speed < 1024:
            unit = u
            break
        speed /= 1024
    return f"{speed:.2f} {unit}"

def format_time(seconds):
    """Format seconds into HH:MM:SS format."""
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{int(hours):02}:{int(minutes):02}:{int(seconds):02}"

def main():
    # ASCII art header
    header = pyfiglet.figlet_format("NIST Disk Imager")
    print(Fore.YELLOW + header)

    # Show credit line
    print(Fore.CYAN + "Credit: Development by DRC Lab/ Nguyen Vu Ha +84903408066 Ha Noi, Viet Nam")

    # Ask user if they want to enable USB write protection
    enable_write_blocker = input(Fore.YELLOW + "Do you want to enable USB Write-blocker? (yes/no): ").strip().lower()

    if enable_write_blocker == 'yes':
        print(Fore.YELLOW + "Enabling write protection for removable disks...")
        if set_write_protect(True):
            print(Fore.GREEN + "Write protection enabled.")
        else:
            print(Fore.RED + "Failed to enable write protection.")
    
    # List all physical disks
    disks = list_physical_disks()
    if not disks:
        print(Fore.RED + "No physical disks found.")
        return

    # Display the list of disks to the user
    print(Fore.CYAN + "\nSelect a physical disk to copy:")
    for idx, (device_id, model) in enumerate(disks):
        print(f"{Fore.GREEN}{idx + 1}: {device_id} ({model})")

    # Get the user's choice
    choice = int(input(Fore.YELLOW + "Enter the number of the disk: ")) - 1
    if choice < 0 or choice >= len(disks):
        print(Fore.RED + "Invalid choice.")
        return

    selected_disk, disk_model = disks[choice]

    # Prompt for the directory path to save the image file
    directory_path = input(Fore.YELLOW + "Enter the directory path to save the image file: ")

    # Ensure the directory exists
    if not os.path.isdir(directory_path):
        print(Fore.RED + "The specified directory does not exist.")
        return

    # Create the full save file path with the disk model as the file name
    save_file_name = f"{disk_model.replace(' ', '_').replace('/', '_')}.img"
    save_file_path = os.path.join(directory_path, save_file_name)

    # Determine block size based on RAM size
    ram_size = get_ram_size()
    if ram_size < 6 * 1024**3:  # Less than 6GB of RAM
        block_size = 16 * 1024 * 1024  # 16MB
    else:
        block_size = 256 * 1024 * 1024  # 256MB

    # Get the disk size
    disk_size = get_disk_size(selected_disk)
    if disk_size == 0:
        print(Fore.RED + "Unable to determine the disk size.")
        return

    total_sectors = disk_size // 512

    def copy_block(offset):
        return read_physical_disk(selected_disk, block_size, offset)

    # Copy the disk to the image file
    try:
        with open(save_file_path, 'wb') as img_file:
            start_time = time.time()
            total_read = 0
            with ThreadPoolExecutor() as executor:
                futures = {executor.submit(copy_block, offset): offset for offset in range(0, disk_size, block_size)}
                for future in futures:
                    block, read_size = future.result()
                    if block is not None:
                        img_file.write(block)
                        total_read += read_size
                    current_time = time.time()
                    elapsed_time = current_time - start_time
                    if elapsed_time > 0:
                        speed = total_read / elapsed_time
                        progress = (total_read / disk_size) * 100
                        remaining_seconds = (disk_size - total_read) / speed if speed > 0 else 0
                        print(f"\r{Fore.CYAN}Progress: {progress:.2f}% | Speed: {format_speed(speed)} | "
                              f"Sectors: {total_read // 512}/{total_sectors} | "
                              f"ETA: {format_time(remaining_seconds)}", end='')
        print(Fore.GREEN + f"\nDisk {selected_disk} copied to {save_file_path} successfully.")
    except Exception as e:
        print(Fore.RED + f"An error occurred: {e}")

if __name__ == "__main__":
    main()

    # Disable write protection after the task is complete
    cleanup_on_exit()