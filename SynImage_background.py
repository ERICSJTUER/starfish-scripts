import numpy as np
import bpy
import starfish
from starfish.rotations import Spherical
from mathutils import Euler
from starfish import utils
import json
import math
import time
import os
import sys
import boto3
import shortuuid
import csv

from collections import defaultdict
import random

def createCSV(name, ds_name):
    header = ['label', 'R', 'G', 'B']
    rows = [
        ['background', '0', '0', '0'],
        ['gateway', '255', '0', '255']
    ]
 
    with open("render/" + ds_name + "/" + "labels_" + str(name) + '0.csv', 'w') as f:
        csv_writer = csv.writer(f)
        csv_writer.writerow(header)
        csv_writer.writerows(rows)
    f.close()

def load_image_into_numpy_array(image):
    (im_width, im_height) = image.size
    image = image.convert('RGB')
    return np.array(image.getdata()).reshape(
        (im_height, im_width, 3)).astype(np.uint8)

def load_images_from_paths(image_paths):
    images = []
    for impath in image_paths:
        image = Image.open(impath)
        image_np = load_image_into_numpy_array(image)
        images.append(image_np)
    return images

def deleteImage(name, ds_name):
    for f in os.listdir(os.getcwd() +'/render/' + ds_name):
        if name in f:
            os.remove(os.getcwd() + '/render/' + ds_name + '/' + f)
    print('--------------------------------- DELETED IMAGE------------------------------')


#********************************************************************************************
############################################
#The following is the main code for image generation
############################################
NUM = 200
SCALE = 17
MOON_RADIUS = 0.4
MOON_CENTERX = 4.723
MOON_CENTERY = 0
def generate(ds_name, tags_list):
    start_time = time.time()

    #check if folder exists in render, if not, create folder
    try:
        os.mkdir("render/" + ds_name)
    except Exception:
        pass
    
    data_storage_path = os.getcwd() + "/render/" + ds_name     
    print(bpy.data.scenes.keys())
    print(bpy.data.worlds["World"].node_tree.nodes['Environment Texture'].image_user.frame_current)
    print(bpy.data.worlds["World"].node_tree.nodes['Environment Texture'].image_user.use_auto_refresh)
    print(bpy.data.images["Moon_1.exr"].name)
    print(bpy.data.images["Moon_1.exr"].filepath_from_user())
    #setting file output stuff
    output_node = bpy.data.scenes["Render"].node_tree.nodes["File Output"]
    output_node.base_path = data_storage_path
    
    #set black background
    #bpy.context.scene.world.color = (0,0,0)
    
    #remove all animation
    for scene in bpy.data.scenes:
        for obj in scene.objects:
            obj.animation_data_clear()
        
    image_num = 0
    shortuuid.set_alphabet('12345678abcdefghijklmnopqrstwxyz')
    # np.random.seed(42)
    poses = utils.random_rotations(NUM)
    lightings = utils.random_rotations(NUM)
    
    moon_num = 1

    for i, (pose, lighting) in enumerate(zip(poses, lightings)):
		
        moon_num = (moon_num + 1) if moon_num < 5 else 1
	
        for scene in bpy.data.scenes:
            scene.unit_settings.scale_length = 1 / SCALE

        nmi = np.random.uniform(low=0.5, high=6)
        distance = nmi * 1852 * SCALE

        if np.random.random() < 0.5:
            # mooon background - uniform distribution over disk slightly larger than moon
            r = MOON_RADIUS/moon_num * np.sqrt(np.random.random())
            t = np.random.uniform(low=0, high=2 * np.pi)
            background = Euler([0, MOON_CENTERX - r * np.cos(t), MOON_CENTERY + r * np.sin(t)])
        else:
            # space background
            
            background = Euler([0, 0, 0])

        offset = np.random.uniform(low=0.0, high=1.0, size=(2,))
		
        bpy.context.scene.frame_set(0)
        frame = starfish.Frame(
            background=background,
            pose=pose,
            lighting=lighting,
            distance=distance,
            offset=offset
        )
        frame.setup(bpy.data.scenes['Real'], bpy.data.objects["Gateway"], bpy.data.objects["Camera"], bpy.data.objects["Sun"])
        
        
        # load new Environment Texture
        image = bpy.data.images.load(filepath = os.getcwd() + "/moon_sequence/{0:04}.exr".format(moon_num))
        bpy.data.worlds["World"].node_tree.nodes['Environment Texture'].image = image
        
        
        glare_value = np.random.beta(0.75, 3) - 1
        bpy.data.scenes["Render"].node_tree.nodes["Glare"].mix = glare_value
		
        #create name for the current image (unique to that image)
        name = shortuuid.uuid() 
        output_node.file_slots[0].path = "image_"+ str(moon_num) +"_"+ str(name) + "#"
        output_node.file_slots[1].path = "mask_" + str(name) + "#"
        
        createCSV(name, ds_name)
        
        image_num = i + 1
        # render
        bpy.ops.render.render(scene="Render")
        
        #Tag the pictures
        frame.tags = tags_list
        # add metadata to frame
        frame.sequence_name = ds_name
        frame.glare_value = glare_value
        
        
    
        with open(os.path.join(output_node.base_path, "meta_" + str(name) + "0.json"), "w") as f:
            f.write(frame.dumps())

    print("===========================================" + "\r")
    time_taken = time.time() - start_time
    print("------Time Taken: %s seconds----------" %(time_taken) + "\r")
    print("Number of images generated: " + str(image_num) + "\r")
    print("Total number of files: " + str(image_num * 5) + "\r")
    print("Average time per image: " + str(time_taken / image_num))
    print("Data stored at: " + data_storage_path)
    bpy.ops.wm.quit_blender()

############################
#The following is the main code for upload
############################
def upload(ds_name, bucket_name):
    print("\n\n______________STARTING UPLOAD_________")

    # Create an S3 client
    s3 = boto3.client('s3')

    print("...begining upload to %s..." % bucket_name) 
    
    try:
        files =next(os.walk(os.getcwd() + "/render/" + ds_name))[2]
    except Exception:
        print("...No data set named " + ds_name + " found in starfish/render. Please generate images with that folder name or move existing folder into render folder")
        exit()
    #count number of files
    num_files = 0
    # For every file in directory
    for file in files:
        #ignore hidden files
        if not file.startswith('.') and not file.startswith('truth'):
            #upload to s3
            print("uploading...")
            sys.stdout.write("\033[F")
            local_file = os.path.join(os.getcwd() + "/render/" + ds_name, file)
            s3.upload_file(local_file, bucket_name, ds_name + "/" + file)
            num_files = num_files + 1

    print("...finished uploading...%d files uploaded..." % num_files)

def validate_bucket_name(bucket_name):
    s3t = boto3.resource('s3')
    #check if bucket exits. If not return false
    if s3t.Bucket(bucket_name).creation_date is None:
        print("...Bucket does not exist, enter valid bucket name...")
        return False
    else:
        #if exists, return true
        print("...bucket exists....")
        return True
#############################################
#Run user input data then run generation/upload
#############################################
def main():
    try:
        os.mkdir("render")
    except Exception:
        pass

    yes = {'yes', 'y', 'Y'}
    runGen = input("*> Generate images?[y/n]: ")
    
    runUpload = input("*> Would you like to upload these images to AWS? [y/n]: ")
    if runUpload in yes: 
        bucket_name = input("*> Enter Bucket name: ")
        #check if bucket name valid
        while not validate_bucket_name(bucket_name):
            bucket_name = input("*> Enter Bucket name: ")
    
    print("   Note: if you want to upload to AWS but not generate images, move folder with images to 'render' and enter folder name. If the folder name exists, images will be stored in that directory")
    dataset_name = input("*> Enter name for folder: ")
    print("   Note: rendered images will be stored in a directory called 'render' in the same local directory this script is located under the directory name you specify.")
    tags = input("*> Enter tags for the batch seperated with space: ")
    tags_list = tags.split();
    if runGen in yes:
        generate(dataset_name, tags_list)
    if runUpload in yes: 
        upload(dataset_name, bucket_name)
    print("______________DONE EXECUTING______________")

if __name__ == "__main__":
    main()
    
