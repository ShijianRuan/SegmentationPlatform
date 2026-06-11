# Renaming tool (Mimics 21.0)
# Source: Materialise Community Forum, Clément Dumont (Materialise), May 2019
# GitHub: https://github.com/clementdum/Renaming-tool
#
# KEY FINDINGS:
# - mask.color exists as RGB tuple (0-1 range): mask.color = (r, g, b)
# - mask.selected exists as bool: if mask.selected == True
# - masks can be renamed and recolored programmatically

import mimics
import pickle
import os.path
import numpy as np
import tkinter as tk
from tkinter.colorchooser import *

def hex_to_rgb(value):
    value = value.lstrip('#')
    lv = len(value)
    return tuple(int(value[i:i + lv // 3], 16) for i in range(0, lv, lv // 3))

pathtofile = os.path.dirname(sys.argv[0]) + r"\data_renaming.p"

class RenamingTool:
    def __init__(self, master):
        self.master = master
        self.opened = 0
        master.title = "Renaming Tool"

        frame_liste = tk.Frame(master)
        frame_liste.grid(row=0, column=0)

        class Name:
            def __init__(self, name, name_color):
                self.name = name
                self.name_color = name_color

        file_exist = os.path.isfile(pathtofile)
        if file_exist:
            data = pickle.load(open(pathtofile, 'rb'))
            liste_names = data[0]
            liste_colors = data[1]
        else:
            liste_names = ["Right Heart", "Left Heart", "Bone", "Stent"]
            liste_colors = ["", "", "", ""]

        list_name = tk.Listbox(frame_liste, selectmode=tk.SINGLE, activestyle="dotbox",
                               selectbackground="white", selectforeground="black")
        list_name.pack()

        ind = 0
        for i in liste_names:
            list_name.insert(tk.END, "  " + i)
        for i in liste_colors:
            if i != '':
                list_name.itemconfig(ind, {'bg': i})
                list_name.itemconfig(ind, {'selectbackground': i})
            ind = ind + 1

        def change_name(event):
            if self.opened == 0:
                new_name_index = list_name.curselection()
                new_name = list_name.get(new_name_index[0])
                color = list_name.itemcget(new_name_index[0], "bg")
                if color != "":
                    color_rgb = np.divide(hex_to_rgb(color), 255)
                    colour = tuple(color_rgb)

                for i in mimics.data.masks:
                    if i.selected == True:
                        i.name = new_name
                        if color != "":
                            i.color = (float(colour[0]), float(colour[1]), float(colour[2]))

        # ... (remaining tkinter UI code omitted for brevity)
        # Full source: https://github.com/clementdum/Renaming-tool
